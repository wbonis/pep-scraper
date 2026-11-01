"""Apply a schedule plan to Yuvomi."""

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
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


class ScheduleClient(Protocol):
    def list_shift_types(self) -> tuple[ExistingType, ...]: ...

    def create_shift_type(self, spec: ShiftTypeSpec) -> int: ...

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


@dataclass(frozen=True, slots=True)
class SyncResult:
    created_types: int
    updated_days: int
    deleted_days: int
    added_extras: int = 0
    deleted_extras: int = 0
    removed_types: int = 0
    tracked_type_ids: frozenset[int] = frozenset()


def sync_schedule(
    events: Iterable[RosterEvent],
    client: ScheduleClient,
    settings: SyncSettings,
    dry_run: bool,
    tracked_type_ids: frozenset[int] = frozenset(),
) -> SyncResult:
    events = tuple(events)
    window = roster_window(events)
    if window is None:
        log.info("Yuvomi: Dienstplan leer, nichts zu tun")
        return SyncResult(0, 0, 0, tracked_type_ids=tracked_type_ids)
    overrides = client.list_overrides(settings.user_id, *window)
    extras = client.list_extras(settings.user_id, *window)
    types = client.list_shift_types()
    plan = plan_schedule(events, types, overrides, extras, settings.absences)
    _log_plan(plan, dry_run)
    if dry_run:
        return _result(plan, removed=0, tracked=tracked_type_ids)
    created = _apply(plan, client, types, settings.user_id)
    used = plan.used_type_ids | frozenset(created.values())
    tracked = tracked_type_ids | frozenset(created.values())
    removed = _remove_unused_types(client, tracked - used)
    return _result(plan, removed=len(removed), tracked=tracked - removed)


def _result(plan: SchedulePlan, removed: int, tracked: frozenset[int]) -> SyncResult:
    return SyncResult(
        created_types=len(plan.create_types),
        updated_days=len(plan.put),
        deleted_days=len(plan.delete),
        added_extras=len(plan.add_extras),
        deleted_extras=len(plan.delete_extras),
        removed_types=removed,
        tracked_type_ids=tracked,
    )


def _apply(
    plan: SchedulePlan,
    client: ScheduleClient,
    types: tuple[ExistingType, ...],
    user_id: int,
) -> dict[str, int]:
    created = {
        type_key(spec): client.create_shift_type(spec) for spec in plan.create_types
    }
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
    return created


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
