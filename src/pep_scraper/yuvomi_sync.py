"""Apply a schedule plan to Yuvomi."""

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from .models import RosterEvent
from .yuvomi_plan import (
    MARKER,
    AbsenceMode,
    ExistingExtra,
    ExistingOverride,
    ExistingType,
    SchedulePlan,
    ShiftTypeSpec,
    plan_schedule,
    resolve_type_id,
    roster_window,
    type_key,
)

log = logging.getLogger(__name__)

Tracked = Mapping[int, str]  # own shift type id -> created_at fingerprint


class ScheduleClient(Protocol):
    def list_shift_types(self) -> tuple[ExistingType, ...]: ...

    def create_shift_type(self, spec: ShiftTypeSpec) -> ExistingType: ...

    def update_shift_type(self, type_id: int, spec: ShiftTypeSpec) -> None: ...

    def delete_shift_type(self, type_id: int) -> bool: ...

    def list_overrides(
        self, user_id: int, start: date, end: date
    ) -> tuple[ExistingOverride, ...]: ...

    def put_override(
        self, user_id: int, day: date, type_id: int | None, note: str
    ) -> None: ...

    def delete_override(self, user_id: int, day: date) -> None: ...

    def list_extras(
        self, user_id: int, start: date, end: date
    ) -> tuple[ExistingExtra, ...]: ...

    def add_extra(self, user_id: int, day: date, type_id: int, note: str) -> None: ...

    def delete_extra(self, extra_id: int) -> None: ...


@dataclass(frozen=True, slots=True)
class SyncSettings:
    user_id: int
    absences: AbsenceMode
    shown_absences: frozenset[str] = frozenset()  # titles named in schichten.toml


@dataclass(frozen=True, slots=True)
class SyncResult:
    created_types: int
    updated_days: int
    deleted_days: int
    added_extras: int = 0
    deleted_extras: int = 0
    removed_types: int = 0
    updated_types: int = 0
    tracked_types: Tracked = field(default_factory=dict)


def sync_schedule(
    events: Iterable[RosterEvent],
    client: ScheduleClient,
    settings: SyncSettings,
    dry_run: bool,
    tracked: Tracked | None = None,
    on_tracked_change: Callable[[dict[int, str]], None] | None = None,
) -> SyncResult:
    """``on_tracked_change`` is called right after new types exist, so they are
    remembered even if a later API call fails."""
    events = tuple(events)
    window = roster_window(events)
    if window is None:
        log.info("Yuvomi: Dienstplan leer, nichts zu tun")
        return SyncResult(0, 0, 0, tracked_types=dict(tracked or {}))
    overrides = client.list_overrides(settings.user_id, *window)
    extras = client.list_extras(settings.user_id, *window)
    types = client.list_shift_types()
    own = _verified_own(tracked or {}, types)
    plan = plan_schedule(
        events,
        types,
        overrides,
        extras,
        settings.absences,
        frozenset(own),
        settings.shown_absences,
    )
    _log_plan(plan, dry_run)
    if dry_run:
        return _result(plan, removed=0, tracked=own)
    created = {type_key(s): client.create_shift_type(s) for s in plan.create_types}
    own = {**own, **{t.id: t.created_at for t in created.values()}}
    if created and on_tracked_change is not None:
        on_tracked_change(own)
    created_ids = {key: t.id for key, t in created.items()}
    _apply(plan, client, types, created_ids, settings.user_id)
    used = plan.used_type_ids | frozenset(created_ids.values())
    fingerprinted = frozenset(k for k, v in own.items() if v)  # no blind deletes
    removed = _remove_unused_types(client, fingerprinted - used)
    remaining = {k: v for k, v in own.items() if k not in removed}
    return _result(plan, removed=len(removed), tracked=remaining)


def _verified_own(tracked: Tracked, types: tuple[ExistingType, ...]) -> dict[int, str]:
    """Keep only tracked ids that still exist with the same fingerprint, so a
    re-used id of somebody else's type is never touched."""
    listed = {t.id: t for t in types}
    own: dict[int, str] = {}
    for type_id, fingerprint in tracked.items():
        current = listed.get(type_id)
        if current is None:
            log.info("Yuvomi: Schichttyp %d gibt es nicht mehr", type_id)
        elif fingerprint and fingerprint != current.created_at:
            log.warning("Yuvomi: Schichttyp %d ist nicht mehr der eigene", type_id)
        else:
            own[type_id] = current.created_at
    return own


def _result(plan: SchedulePlan, removed: int, tracked: dict[int, str]) -> SyncResult:
    return SyncResult(
        created_types=len(plan.create_types),
        updated_days=len(plan.put),
        deleted_days=len(plan.delete),
        added_extras=len(plan.add_extras),
        deleted_extras=len(plan.delete_extras),
        removed_types=removed,
        updated_types=len(plan.update_types),
        tracked_types=tracked,
    )


def _apply(
    plan: SchedulePlan,
    client: ScheduleClient,
    types: tuple[ExistingType, ...],
    created: Mapping[str, int],
    user_id: int,
) -> None:
    for own_id, new_spec in plan.update_types:
        client.update_shift_type(own_id, new_spec)
    for assignment in plan.put:
        spec = assignment.spec
        type_id = None if spec is None else _type_id(spec, types, created)
        client.put_override(user_id, assignment.day, type_id, MARKER)
    for day in plan.delete:
        client.delete_override(user_id, day)
    for extra_id in plan.delete_extras:
        client.delete_extra(extra_id)
    for assignment in plan.add_extras:
        if assignment.spec is not None:
            type_id = _type_id(assignment.spec, types, created)
            client.add_extra(user_id, assignment.day, type_id, MARKER)


def _type_id(
    spec: ShiftTypeSpec, types: tuple[ExistingType, ...], created: Mapping[str, int]
) -> int:
    type_id = resolve_type_id(spec, types)
    return created[type_key(spec)] if type_id is None else type_id


def _remove_unused_types(
    client: ScheduleClient, candidates: frozenset[int]
) -> frozenset[int]:
    """Delete own shift types LOGA no longer uses. Yuvomi refuses (409) while
    past days still reference them; those stay for the history."""
    removed = frozenset(t for t in sorted(candidates) if client.delete_shift_type(t))
    for type_id in sorted(removed):
        log.info("Yuvomi: ungenutzten Schichttyp %d entfernt", type_id)
    return removed


def _log_plan(plan: SchedulePlan, dry_run: bool) -> None:
    prefix = "Yuvomi (Probelauf)" if dry_run else "Yuvomi"
    for spec in plan.create_types:
        log.info("%s: lege Schichttyp an: %s", prefix, spec.name)
    for type_id, spec in plan.update_types:
        log.info(
            "%s: aktualisiere Schichttyp %d: %s %s-%s",
            prefix,
            type_id,
            spec.name,
            spec.start_time or "",
            spec.end_time or "",
        )
    for assignment in plan.put:
        label = "frei" if assignment.spec is None else assignment.spec.name
        log.info("%s: setze %s -> %s", prefix, assignment.day.isoformat(), label)
    for day in plan.delete:
        log.info("%s: entferne Eintrag %s", prefix, day.isoformat())
    for assignment in plan.add_extras:
        name = assignment.spec.name if assignment.spec else "?"
        log.info("%s: Zusatzdienst %s -> %s", prefix, assignment.day.isoformat(), name)
    for extra_id in plan.delete_extras:
        log.info("%s: entferne Zusatzdienst %d", prefix, extra_id)
    if plan.is_empty:
        log.info("%s: Schichtplan ist aktuell", prefix)
