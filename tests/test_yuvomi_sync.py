from dataclasses import dataclass, field
from datetime import date, datetime

from pep_scraper.models import RosterEvent
from pep_scraper.yuvomi_plan import (
    MARKER,
    AbsenceMode,
    ExistingExtra,
    ExistingOverride,
    ExistingType,
    ShiftTypeSpec,
)
from pep_scraper.yuvomi_sync import SyncSettings, sync_schedule


@dataclass
class FakeClient:
    types: list[ExistingType] = field(default_factory=list)
    overrides: list[ExistingOverride] = field(default_factory=list)
    extras: list[ExistingExtra] = field(default_factory=list)
    in_use: set[int] = field(default_factory=set)
    calls: list[tuple[object, ...]] = field(default_factory=list)

    def list_shift_types(self) -> tuple[ExistingType, ...]:
        return tuple(self.types)

    def create_shift_type(self, spec: ShiftTypeSpec) -> ExistingType:
        self.calls.append(("create", spec.short_code))
        new_id = 100 + len(self.calls)
        return ExistingType(new_id, spec.short_code, spec.name, spec.icon, f"c{new_id}")

    def update_shift_type(self, type_id: int, spec: ShiftTypeSpec) -> None:
        self.calls.append(("update_type", type_id, spec.name, spec.icon))

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

    def list_extras(
        self, user_id: int, start: date, end: date
    ) -> tuple[ExistingExtra, ...]:
        return tuple(self.extras)

    def add_extra(self, user_id: int, day: date, type_id: int, note: str) -> None:
        self.calls.append(("add_extra", user_id, day, type_id, note))

    def delete_extra(self, extra_id: int) -> None:
        self.calls.append(("delete_extra", extra_id))

    def delete_shift_type(self, type_id: int) -> bool:
        self.calls.append(("delete_type", type_id))
        return type_id not in self.in_use


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


def _shift_at(day: int, code: str, start: int, end: int) -> RosterEvent:
    return RosterEvent(
        uid=f"{code}{day}",
        summary=f"{code} x",
        description="",
        start=datetime(2026, 11, day, start),
        end=datetime(2026, 11, day, end),
        all_day=False,
        kind="shift",
        code=code,
        color="#ABB3FF",
    )


def test_sync_writes_extra_shift() -> None:
    client = FakeClient(types=[ExistingType(1, "S1", "a"), ExistingType(2, "S2", "b")])
    events = (_shift_at(5, "S1", 6, 10), _shift_at(5, "S2", 16, 20))
    result = sync_schedule(events, client, SETTINGS, dry_run=False)
    assert ("add_extra", 4, date(2026, 11, 5), 2, MARKER) in client.calls
    assert result.added_extras == 1


def test_sync_removes_unused_tracked_types_only() -> None:
    types = [
        ExistingType(7, "N003", "Nacht", None, "a"),
        ExistingType(20, "X", "x", None, "b"),
        ExistingType(21, "Y", "y", None, "c"),
    ]
    client = FakeClient(types=types, in_use={21})
    result = sync_schedule(
        (_night(1),),
        client,
        SETTINGS,
        dry_run=False,
        tracked={7: "a", 20: "b", 21: "c"},
    )
    deleted = [c[1] for c in client.calls if c[0] == "delete_type"]
    assert deleted == [20, 21]  # 7 still needed -> never tried
    assert result.removed_types == 1
    assert dict(result.tracked_types) == {
        7: "a",
        21: "c",
    }  # 21 in use (history) -> keep


def test_tracked_id_with_other_fingerprint_is_never_deleted() -> None:
    client = FakeClient(types=[ExistingType(20, "X", "fremd", None, "2027-01-01")])
    result = sync_schedule(
        (_night(1),),
        client,
        SETTINGS,
        dry_run=False,
        tracked={20: "2026-11-01", 30: "z"},
    )
    assert not [c for c in client.calls if c[0] == "delete_type"]
    assert 20 not in result.tracked_types and 30 not in result.tracked_types


def test_legacy_tracked_id_adopts_fingerprint() -> None:
    client = FakeClient(types=[ExistingType(7, "N003", "Nacht", None, "2026-11-01")])
    result = sync_schedule(
        (_night(1),), client, SETTINGS, dry_run=False, tracked={7: ""}
    )
    assert dict(result.tracked_types) == {7: "2026-11-01"}


def test_sync_tracks_newly_created_types() -> None:
    client = FakeClient()
    result = sync_schedule((_night(1),), client, SETTINGS, dry_run=False)
    assert dict(result.tracked_types) == {102: "c102"}


def test_created_types_reported_before_later_failure() -> None:
    import pytest

    from pep_scraper.yuvomi_client import YuvomiError

    class FailingPut(FakeClient):
        def put_override(self, *_a: object) -> None:
            raise YuvomiError("HTTP 500")

    seen: list[dict[int, str]] = []
    with pytest.raises(YuvomiError):
        sync_schedule(
            (_night(1),),
            FailingPut(),
            SETTINGS,
            dry_run=False,
            on_tracked_change=seen.append,
        )
    assert seen == [{102: "c102"}]


def test_own_type_renamed() -> None:
    from dataclasses import replace

    client = FakeClient(types=[ExistingType(7, "N003", "N003 21:45-06:15", None, "t")])
    night = replace(_night(1), summary="Nachtdienst", icon="moon")
    result = sync_schedule((night,), client, SETTINGS, dry_run=False, tracked={7: "t"})
    assert ("update_type", 7, "Nachtdienst", "moon") in client.calls
    assert result.updated_types == 1


def test_dry_run_tries_no_type_cleanup() -> None:
    client = FakeClient(types=[ExistingType(20, "X", "x")])
    result = sync_schedule(
        (_night(1),), client, SETTINGS, dry_run=True, tracked={20: ""}
    )
    assert not [c for c in client.calls if c[0] in ("delete_type", "update_type")]
    assert dict(result.tracked_types) == {20: ""}


def test_type_without_fingerprint_is_never_deleted() -> None:
    client = FakeClient(
        types=[ExistingType(7, "N003", "Nacht"), ExistingType(20, "X", "x")]
    )
    sync_schedule((_night(1),), client, SETTINGS, dry_run=False, tracked={20: ""})
    assert not [c for c in client.calls if c[0] == "delete_type"]
