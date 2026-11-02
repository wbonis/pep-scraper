"""Pure planning: roster events -> changes for the Yuvomi shift schedule.

One entry per day and person (Yuvomi "override") for the first shift; further
shifts on the same day become Yuvomi "extras". LOGA wins on every roster day,
also over a manual entry. Entries written by this tool carry exactly
``MARKER`` as note; stale cleanup deletes only those, so manual entries on
days LOGA does not cover stay untouched.
"""

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from .models import RosterEvent
from .naming import is_health_reason, is_shown_absence

log = logging.getLogger(__name__)

MARKER = "pep-scraper"
DEFAULT_COLOR = "#0891B2"
ABSENCE_COLOR = "#78808C"
ABSENCE_ICON = "calendar-off"
MAX_SHORT_CODE = 12


class AbsenceMode(Enum):
    NEUTRAL = "neutral"  # harmless/named titles shown, everything else "Abwesend"
    HIDDEN = "hidden"  # every absence as "Abwesend"
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
    icon: str | None = None
    created_at: str = ""
    start_time: str | None = None  # "HH:MM"; None = Yuvomi did not report it
    end_time: str | None = None


@dataclass(frozen=True, slots=True)
class ExistingOverride:
    day: date
    shift_type_id: int | None
    note: str

    @property
    def is_ours(self) -> bool:
        return self.note.strip() == MARKER


@dataclass(frozen=True, slots=True)
class ExistingExtra:
    """Additional shift on a day (Yuvomi "extra"), addressed by id."""

    id: int
    day: date
    shift_type_id: int
    note: str

    @property
    def is_ours(self) -> bool:
        return self.note.strip() == MARKER


@dataclass(frozen=True, slots=True)
class DayPlan:
    primary: ShiftTypeSpec | None  # None = explicit day off
    extras: tuple[ShiftTypeSpec, ...]


@dataclass(frozen=True, slots=True)
class DayAssignment:
    day: date
    spec: ShiftTypeSpec | None  # None = explicit day off


@dataclass(frozen=True, slots=True)
class SchedulePlan:
    create_types: tuple[ShiftTypeSpec, ...]
    put: tuple[DayAssignment, ...]
    delete: tuple[date, ...]
    add_extras: tuple[DayAssignment, ...] = ()
    delete_extras: tuple[int, ...] = ()
    used_type_ids: frozenset[int] = frozenset()
    update_types: tuple[tuple[int, ShiftTypeSpec], ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (
            self.create_types
            or self.update_types
            or self.put
            or self.delete
            or self.add_extras
            or self.delete_extras
        )


def event_day(event: RosterEvent) -> date:
    if isinstance(event.start, datetime):
        return event.start.date()
    return event.start


def roster_window(events: Iterable[RosterEvent]) -> tuple[date, date] | None:
    days = sorted(event_day(e) for e in events)
    return (days[0], days[-1]) if days else None


def desired_days(
    events: Iterable[RosterEvent],
    mode: AbsenceMode,
    shown_absences: frozenset[str] = frozenset(),
) -> dict[date, DayPlan]:
    by_day: dict[date, list[RosterEvent]] = {}
    for event in events:
        by_day.setdefault(event_day(event), []).append(event)
    result: dict[date, DayPlan] = {}
    for day in sorted(by_day):
        day_events = by_day[day]
        has_absence = any(e.kind == "absence" for e in day_events)
        if has_absence and mode is AbsenceMode.SKIP:
            continue
        result[day] = _choose(day_events, mode, shown_absences)
    return result


def _choose(
    events: list[RosterEvent], mode: AbsenceMode, shown_absences: frozenset[str]
) -> DayPlan:
    """Absence beats shifts beat free day. First shift is primary, rest extras."""
    absences = [e for e in events if e.kind == "absence"]
    if absences:
        return DayPlan(_absence_spec(absences[0], mode, shown_absences), ())
    shifts = sorted((e for e in events if e.kind == "shift"), key=lambda e: e.start)
    if shifts:
        specs = tuple(_shift_spec(e) for e in shifts)
        return DayPlan(specs[0], specs[1:])
    return DayPlan(None, ())


def _absence_spec(
    event: RosterEvent, mode: AbsenceMode, shown_absences: frozenset[str]
) -> ShiftTypeSpec:
    hide = mode is AbsenceMode.HIDDEN or (
        mode is AbsenceMode.NEUTRAL and not is_shown_absence(event.code, shown_absences)
    )
    if hide:
        if mode is AbsenceMode.NEUTRAL and not is_health_reason(event.code):
            log.info(
                "Abwesenheit %r als 'Abwesend' eingetragen - in schichten.toml "
                "eintragen, um den Titel zu zeigen",
                event.code,
            )
        return NEUTRAL_ABSENCE
    icon = event.icon or ABSENCE_ICON
    start, end = _times(event) if not event.all_day else (None, None)
    return ShiftTypeSpec(None, event.summary, start, end, ABSENCE_COLOR, icon)


def _times(event: RosterEvent) -> tuple[str, str]:
    if not (isinstance(event.start, datetime) and isinstance(event.end, datetime)):
        raise TypeError(f"{event.summary!r} needs start/end datetimes")
    return event.start.strftime("%H:%M"), event.end.strftime("%H:%M")


def _shift_spec(event: RosterEvent) -> ShiftTypeSpec:
    start, end = _times(event)
    return ShiftTypeSpec(
        short_code=event.code[:MAX_SHORT_CODE] or None,
        name=event.summary,
        start_time=start,
        end_time=end,
        color=event.color or DEFAULT_COLOR,
        icon=event.icon,
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
    existing_extras: Iterable[ExistingExtra],
    mode: AbsenceMode,
    own_type_ids: frozenset[int] = frozenset(),
    shown_absences: frozenset[str] = frozenset(),
) -> SchedulePlan:
    events = tuple(events)
    window = roster_window(events)
    if window is None:
        return SchedulePlan((), (), ())
    types = tuple(existing_types)
    overrides = {o.day: o for o in existing_overrides}
    desired = desired_days(events, mode, shown_absences)
    specs = tuple(_all_specs(desired.values()))
    add_extras, delete_extras = _extra_changes(desired, types, existing_extras, window)
    return SchedulePlan(
        create_types=_missing_types(specs, types),
        put=_changed_days(desired, types, overrides),
        delete=_stale_days(desired, overrides, window),
        add_extras=add_extras,
        delete_extras=delete_extras,
        used_type_ids=frozenset(
            tid for spec in specs if (tid := resolve_type_id(spec, types)) is not None
        ),
        update_types=_renamed_types(specs, types, own_type_ids),
    )


def _renamed_types(
    specs: Iterable[ShiftTypeSpec],
    types: tuple[ExistingType, ...],
    own_type_ids: frozenset[int],
) -> tuple[tuple[int, ShiftTypeSpec], ...]:
    """Own types whose name, icon or times no longer match (e.g. new
    schichten.toml or break setting). Times count only if both sides have them."""
    by_id = {t.id: t for t in types}
    updates: dict[int, ShiftTypeSpec] = {}
    for spec in specs:
        type_id = resolve_type_id(spec, types)
        if type_id is None or type_id not in own_type_ids or type_id in updates:
            continue
        if _differs(by_id[type_id], spec):
            updates[type_id] = spec
    return tuple(sorted(updates.items()))


def _differs(current: ExistingType, spec: ShiftTypeSpec) -> bool:
    if (current.name, current.icon) != (spec.name, spec.icon):
        return True
    current_times = (current.start_time, current.end_time)
    spec_times = (spec.start_time, spec.end_time)
    if (None, None) in (current_times, spec_times):
        return False
    return (current.start_time, current.end_time) != (spec.start_time, spec.end_time)


def _all_specs(days: Iterable[DayPlan]) -> Iterable[ShiftTypeSpec]:
    for day in days:
        if day.primary is not None:
            yield day.primary
        yield from day.extras


def _missing_types(
    specs: Iterable[ShiftTypeSpec], types: tuple[ExistingType, ...]
) -> tuple[ShiftTypeSpec, ...]:
    missing: dict[str, ShiftTypeSpec] = {}
    for spec in specs:
        if resolve_type_id(spec, types) is None:
            missing.setdefault(type_key(spec), spec)
    return tuple(missing.values())


def _changed_days(
    desired: Mapping[date, DayPlan],
    types: tuple[ExistingType, ...],
    overrides: Mapping[date, ExistingOverride],
) -> tuple[DayAssignment, ...]:
    changed = []
    for day, plan in desired.items():
        spec = plan.primary
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
    desired: Mapping[date, DayPlan],
    overrides: Mapping[date, ExistingOverride],
    window: tuple[date, date],
) -> tuple[date, ...]:
    first, last = window
    return tuple(
        day
        for day, override in sorted(overrides.items())
        if override.is_ours and first <= day <= last and day not in desired
    )


def _extra_changes(
    desired: Mapping[date, DayPlan],
    types: tuple[ExistingType, ...],
    existing: Iterable[ExistingExtra],
    window: tuple[date, date],
) -> tuple[tuple[DayAssignment, ...], tuple[int, ...]]:
    """Match wanted extras against our own existing ones, day by day."""
    first, last = window
    ours: dict[date, list[ExistingExtra]] = {}
    for extra in existing:
        if extra.is_ours and first <= extra.day <= last:
            ours.setdefault(extra.day, []).append(extra)
    to_add: list[DayAssignment] = []
    to_delete: list[int] = []
    for day in sorted(set(desired) | set(ours)):
        wanted = desired[day].extras if day in desired else ()
        leftover = list(ours.get(day, ()))
        for spec in wanted:
            type_id = resolve_type_id(spec, types)
            match = next((e for e in leftover if e.shift_type_id == type_id), None)
            if match is None:
                to_add.append(DayAssignment(day, spec))
            else:
                leftover.remove(match)
        to_delete.extend(e.id for e in leftover)
    return tuple(to_add), tuple(to_delete)
