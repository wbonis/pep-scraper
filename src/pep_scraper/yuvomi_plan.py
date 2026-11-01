"""Pure planning: roster events -> changes for the Yuvomi shift schedule.

One entry per day and person (Yuvomi "override"). LOGA wins on every roster
day, also over a manual entry. Days written by this tool carry exactly
``MARKER`` as note; stale-day cleanup deletes only those, so manual entries on
days LOGA does not cover stay untouched.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from .models import RosterEvent

MARKER = "pep-scraper"
DEFAULT_COLOR = "#0891B2"
ABSENCE_COLOR = "#78808C"
ABSENCE_ICON = "calendar-off"
MAX_SHORT_CODE = 12


class AbsenceMode(Enum):
    NEUTRAL = "neutral"  # every absence as "Abwesend", reason hidden
    DETAIL = "detail"  # one shift type per reason (Urlaub, Krank, ...)
    SKIP = "skip"  # absence days are not written


@dataclass(frozen=True, slots=True)
class ShiftTypeSpec:
    short_code: str | None
    name: str
    start_time: str | None
    end_time: str | None
    color: str
    icon: str | None = None


NEUTRAL_ABSENCE = ShiftTypeSpec(
    "ABW", "Abwesend", None, None, ABSENCE_COLOR, ABSENCE_ICON
)


@dataclass(frozen=True, slots=True)
class ExistingType:
    id: int
    short_code: str | None
    name: str


@dataclass(frozen=True, slots=True)
class ExistingOverride:
    day: date
    shift_type_id: int | None
    note: str

    @property
    def is_ours(self) -> bool:
        return self.note.strip() == MARKER


@dataclass(frozen=True, slots=True)
class DayAssignment:
    day: date
    spec: ShiftTypeSpec | None  # None = explicit day off


@dataclass(frozen=True, slots=True)
class SchedulePlan:
    create_types: tuple[ShiftTypeSpec, ...]
    put: tuple[DayAssignment, ...]
    delete: tuple[date, ...]

    @property
    def is_empty(self) -> bool:
        return not (self.create_types or self.put or self.delete)


def event_day(event: RosterEvent) -> date:
    if isinstance(event.start, datetime):
        return event.start.date()
    return event.start


def roster_window(events: Iterable[RosterEvent]) -> tuple[date, date] | None:
    days = sorted(event_day(e) for e in events)
    return (days[0], days[-1]) if days else None


def desired_days(
    events: Iterable[RosterEvent], mode: AbsenceMode
) -> dict[date, ShiftTypeSpec | None]:
    by_day: dict[date, list[RosterEvent]] = {}
    for event in events:
        by_day.setdefault(event_day(event), []).append(event)
    result: dict[date, ShiftTypeSpec | None] = {}
    for day in sorted(by_day):
        day_events = by_day[day]
        has_absence = any(e.kind == "absence" for e in day_events)
        if has_absence and mode is AbsenceMode.SKIP:
            continue
        result[day] = _choose(day_events, mode)
    return result


def _choose(events: list[RosterEvent], mode: AbsenceMode) -> ShiftTypeSpec | None:
    """Absence beats shift beats free day."""
    absences = [e for e in events if e.kind == "absence"]
    if absences:
        if mode is AbsenceMode.NEUTRAL:
            return NEUTRAL_ABSENCE
        return ShiftTypeSpec(
            None, absences[0].summary, None, None, ABSENCE_COLOR, ABSENCE_ICON
        )
    shifts = sorted((e for e in events if e.kind == "shift"), key=lambda e: e.start)
    if shifts:
        return _shift_spec(shifts[0])
    return None


def _shift_spec(event: RosterEvent) -> ShiftTypeSpec:
    if not (isinstance(event.start, datetime) and isinstance(event.end, datetime)):
        raise TypeError(f"shift {event.summary!r} needs start/end datetimes")
    return ShiftTypeSpec(
        short_code=event.code[:MAX_SHORT_CODE] or None,
        name=event.summary,
        start_time=event.start.strftime("%H:%M"),
        end_time=event.end.strftime("%H:%M"),
        color=event.color or DEFAULT_COLOR,
    )


def type_key(spec: ShiftTypeSpec) -> str:
    if spec.short_code:
        return f"code:{spec.short_code.casefold()}"
    return f"name:{spec.name.casefold()}"


def resolve_type_id(
    spec: ShiftTypeSpec, existing: Iterable[ExistingType]
) -> int | None:
    types = tuple(existing)
    if spec.short_code:
        wanted = spec.short_code.casefold()
        for t in types:
            if t.short_code and t.short_code.casefold() == wanted:
                return t.id
    wanted_name = spec.name.casefold()
    return next((t.id for t in types if t.name.casefold() == wanted_name), None)


def plan_schedule(
    events: Iterable[RosterEvent],
    existing_types: Iterable[ExistingType],
    existing_overrides: Iterable[ExistingOverride],
    mode: AbsenceMode,
) -> SchedulePlan:
    events = tuple(events)
    window = roster_window(events)
    if window is None:
        return SchedulePlan((), (), ())
    types = tuple(existing_types)
    overrides = {o.day: o for o in existing_overrides}
    desired = desired_days(events, mode)
    return SchedulePlan(
        create_types=_missing_types(desired.values(), types),
        put=_changed_days(desired, types, overrides),
        delete=_stale_days(desired, overrides, window),
    )


def _missing_types(
    specs: Iterable[ShiftTypeSpec | None], types: tuple[ExistingType, ...]
) -> tuple[ShiftTypeSpec, ...]:
    missing: dict[str, ShiftTypeSpec] = {}
    for spec in specs:
        if spec is not None and resolve_type_id(spec, types) is None:
            missing.setdefault(type_key(spec), spec)
    return tuple(missing.values())


def _changed_days(
    desired: Mapping[date, ShiftTypeSpec | None],
    types: tuple[ExistingType, ...],
    overrides: Mapping[date, ExistingOverride],
) -> tuple[DayAssignment, ...]:
    changed = []
    for day, spec in desired.items():
        current = overrides.get(day)
        wanted_id = None if spec is None else resolve_type_id(spec, types)
        unchanged = (
            current is not None
            and current.is_ours
            and (spec is None or wanted_id is not None)
            and current.shift_type_id == wanted_id
        )
        if not unchanged:
            changed.append(DayAssignment(day, spec))
    return tuple(changed)


def _stale_days(
    desired: Mapping[date, ShiftTypeSpec | None],
    overrides: Mapping[date, ExistingOverride],
    window: tuple[date, date],
) -> tuple[date, ...]:
    first, last = window
    return tuple(
        day
        for day, override in sorted(overrides.items())
        if override.is_ours and first <= day <= last and day not in desired
    )
