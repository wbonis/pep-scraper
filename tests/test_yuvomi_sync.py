from dataclasses import dataclass, field
from datetime import date, datetime

from pep_scraper.models import RosterEvent
from pep_scraper.yuvomi_plan import (
    MARKER,
    AbsenceMode,
    ExistingOverride,
    ExistingType,
    ShiftTypeSpec,
)
from pep_scraper.yuvomi_sync import SyncSettings, sync_schedule


@dataclass
class FakeClient:
    types: list[ExistingType] = field(default_factory=list)
    overrides: list[ExistingOverride] = field(default_factory=list)
    calls: list[tuple[object, ...]] = field(default_factory=list)

    def list_shift_types(self) -> tuple[ExistingType, ...]:
        return tuple(self.types)

    def create_shift_type(self, spec: ShiftTypeSpec) -> int:
        self.calls.append(("create", spec.short_code))
        return 100 + len(self.calls)

    def list_overrides(
        self, user_id: int, start: date, end: date
    ) -> tuple[ExistingOverride, ...]:
        self.calls.append(("list_overrides", user_id, start, end))
        return tuple(self.overrides)

    def put_override(
        self, user_id: int, day: date, type_id: int | None, note: str
    ) -> None:
        self.calls.append(("put", user_id, day, type_id, note))

    def delete_override(self, user_id: int, day: date) -> None:
        self.calls.append(("delete", user_id, day))


def _night(day: int) -> RosterEvent:
    return RosterEvent(
        uid=f"n{day}",
        summary="N003 21:45-06:15",
        description="",
        start=datetime(2026, 11, day, 21, 45),
        end=datetime(2026, 11, day + 1, 6, 15),
        all_day=False,
        kind="shift",
        code="N003",
        color="#ABB3FF",
    )


SETTINGS = SyncSettings(user_id=4, absences=AbsenceMode.NEUTRAL)


def test_sync_creates_type_and_puts_days() -> None:
    client = FakeClient(overrides=[ExistingOverride(date(2026, 11, 3), 9, MARKER)])
    result = sync_schedule((_night(1), _night(5)), client, SETTINGS, dry_run=False)
    assert ("list_overrides", 4, date(2026, 11, 1), date(2026, 11, 5)) in client.calls
    assert client.calls[1] == ("create", "N003")
    type_id = 102
    assert ("put", 4, date(2026, 11, 1), type_id, MARKER) in client.calls
    assert ("put", 4, date(2026, 11, 5), type_id, MARKER) in client.calls
    assert ("delete", 4, date(2026, 11, 3)) in client.calls
    assert (result.created_types, result.updated_days, result.deleted_days) == (1, 2, 1)


def test_dry_run_writes_nothing() -> None:
    client = FakeClient()
    result = sync_schedule((_night(1),), client, SETTINGS, dry_run=True)
    assert [c[0] for c in client.calls] == ["list_overrides"]
    assert (result.created_types, result.updated_days) == (1, 1)


def test_empty_roster_no_calls() -> None:
    client = FakeClient()
    result = sync_schedule((), client, SETTINGS, dry_run=False)
    assert client.calls == []
    assert result.updated_days == 0


def test_existing_type_reused() -> None:
    client = FakeClient(types=[ExistingType(7, "n003", "Nacht")])
    sync_schedule((_night(1),), client, SETTINGS, dry_run=False)
    assert ("put", 4, date(2026, 11, 1), 7, MARKER) in client.calls
    assert not [c for c in client.calls if c[0] == "create"]
