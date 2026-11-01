"""Apply a schedule plan to Yuvomi."""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from .models import RosterEvent
from .yuvomi_plan import (
    MARKER,
    AbsenceMode,
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

    def list_overrides(
        self, user_id: int, start: date, end: date
    ) -> tuple[ExistingOverride, ...]: ...

    def put_override(
        self, user_id: int, day: date, type_id: int | None, note: str
    ) -> None: ...

    def delete_override(self, user_id: int, day: date) -> None: ...


@dataclass(frozen=True, slots=True)
class SyncSettings:
    user_id: int
    absences: AbsenceMode


@dataclass(frozen=True, slots=True)
class SyncResult:
    created_types: int
    updated_days: int
    deleted_days: int


def sync_schedule(
    events: Iterable[RosterEvent],
    client: ScheduleClient,
    settings: SyncSettings,
    dry_run: bool,
) -> SyncResult:
    events = tuple(events)
    window = roster_window(events)
    if window is None:
        log.info("yuvomi: empty roster, nothing to sync")
        return SyncResult(0, 0, 0)
    overrides = client.list_overrides(settings.user_id, *window)
    types = client.list_shift_types()
    plan = plan_schedule(events, types, overrides, settings.absences)
    _log_plan(plan, dry_run)
    if not dry_run:
        _apply(plan, client, types, settings.user_id)
    return SyncResult(len(plan.create_types), len(plan.put), len(plan.delete))


def _apply(
    plan: SchedulePlan,
    client: ScheduleClient,
    types: tuple[ExistingType, ...],
    user_id: int,
) -> None:
    created = {
        type_key(spec): client.create_shift_type(spec) for spec in plan.create_types
    }
    for assignment in plan.put:
        spec = assignment.spec
        type_id = None
        if spec is not None:
            type_id = resolve_type_id(spec, types)
            if type_id is None:
                type_id = created[type_key(spec)]
        client.put_override(user_id, assignment.day, type_id, MARKER)
    for day in plan.delete:
        client.delete_override(user_id, day)


def _log_plan(plan: SchedulePlan, dry_run: bool) -> None:
    prefix = "yuvomi (dry-run)" if dry_run else "yuvomi"
    for spec in plan.create_types:
        log.info("%s: create shift type %s", prefix, spec.name)
    for assignment in plan.put:
        label = "frei" if assignment.spec is None else assignment.spec.name
        log.info("%s: set %s -> %s", prefix, assignment.day.isoformat(), label)
    for day in plan.delete:
        log.info("%s: remove %s", prefix, day.isoformat())
    if plan.is_empty:
        log.info("%s: schedule already up to date", prefix)
