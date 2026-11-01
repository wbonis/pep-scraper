from datetime import date, datetime

import pytest

from pep_scraper.models import RosterEvent
from pep_scraper.yuvomi_plan import (
    MARKER,
    NEUTRAL_ABSENCE,
    AbsenceMode,
    ExistingOverride,
    ExistingType,
    ShiftTypeSpec,
    desired_days,
    plan_schedule,
    resolve_type_id,
)


def _shift(day: int, code: str = "N003", start: int = 21, end: int = 6) -> RosterEvent:
    end_day = day + 1 if end < start else day
    return RosterEvent(
        uid=f"s{day}{code}",
        summary=f"{code} {start:02d}:00-{end:02d}:00",
        description="Station 1",
        start=datetime(2026, 11, day, start),
        end=datetime(2026, 11, end_day, end),
        all_day=False,
        kind="shift",
        code=code,
        color="#ABB3FF",
    )


def _all_day(day: int, kind: str, title: str) -> RosterEvent:
    return RosterEvent(
        uid=f"a{day}{title}",
        summary=title,
        description="",
        start=date(2026, 11, day),
        end=date(2026, 11, day + 1),
        all_day=True,
        kind=kind,  # type: ignore[arg-type]
        code="FREI" if kind == "free" else title,
    )


N003 = ShiftTypeSpec("N003", "N003 21:00-06:00", "21:00", "06:00", "#ABB3FF")


def test_shift_becomes_spec_with_times_and_color() -> None:
    days = desired_days((_shift(5),), AbsenceMode.NEUTRAL)
    assert days == {date(2026, 11, 5): N003}


def test_free_day_is_none() -> None:
    days = desired_days((_all_day(3, "free", "FREI x"),), AbsenceMode.NEUTRAL)
    assert days == {date(2026, 11, 3): None}


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (AbsenceMode.NEUTRAL, NEUTRAL_ABSENCE),
        (
            AbsenceMode.DETAIL,
            ShiftTypeSpec(None, "Krank mit EFZ", None, None, "#78808C", "calendar-off"),
        ),
    ],
)
def test_absence_wins_over_shift(mode: AbsenceMode, expected: ShiftTypeSpec) -> None:
    events = (_shift(1), _all_day(1, "absence", "Krank mit EFZ"))
    assert desired_days(events, mode) == {date(2026, 11, 1): expected}


def test_skip_mode_leaves_absence_day_out() -> None:
    events = (_shift(1), _all_day(1, "absence", "Krank mit EFZ"), _shift(2))
    assert set(desired_days(events, AbsenceMode.SKIP)) == {date(2026, 11, 2)}


def test_resolve_type_by_code_then_name() -> None:
    existing = (ExistingType(4, "U", "Urlaub"), ExistingType(7, "N003", "Nacht"))
    assert resolve_type_id(N003, existing) == 7
    urlaub = ShiftTypeSpec(None, "urlaub", None, None, "#78808C")
    assert resolve_type_id(urlaub, existing) == 4
    assert resolve_type_id(NEUTRAL_ABSENCE, existing) is None


def test_plan_creates_missing_types_once() -> None:
    plan = plan_schedule((_shift(5), _shift(6)), (), (), AbsenceMode.NEUTRAL)
    assert plan.create_types == (N003,)
    assert [a.day for a in plan.put] == [date(2026, 11, 5), date(2026, 11, 6)]


def test_plan_skips_unchanged_own_override() -> None:
    types = (ExistingType(7, "N003", "x"),)
    overrides = (ExistingOverride(date(2026, 11, 5), 7, MARKER),)
    plan = plan_schedule((_shift(5),), types, overrides, AbsenceMode.NEUTRAL)
    assert plan.put == () and plan.delete == () and plan.create_types == ()


def test_plan_overwrites_manual_override_on_roster_day() -> None:
    types = (ExistingType(7, "N003", "x"),)
    overrides = (ExistingOverride(date(2026, 11, 5), 7, "von Hand"),)
    plan = plan_schedule((_shift(5),), types, overrides, AbsenceMode.NEUTRAL)
    assert [a.day for a in plan.put] == [date(2026, 11, 5)]


def test_plan_deletes_only_own_stale_overrides_in_window() -> None:
    events = (_shift(5), _shift(9))
    overrides = (
        ExistingOverride(date(2026, 11, 7), 7, MARKER),  # ours, gone -> delete
        ExistingOverride(date(2026, 11, 8), 7, "manuell"),  # manual -> keep
        ExistingOverride(date(2026, 11, 20), 7, MARKER),  # outside window -> keep
    )
    plan = plan_schedule(events, (), overrides, AbsenceMode.NEUTRAL)
    assert plan.delete == (date(2026, 11, 7),)


def test_plan_empty_roster_changes_nothing() -> None:
    overrides = (ExistingOverride(date(2026, 11, 7), 7, MARKER),)
    plan = plan_schedule((), (), overrides, AbsenceMode.NEUTRAL)
    assert plan.is_empty


@pytest.mark.parametrize(
    ("note", "ours"),
    [
        ("pep-scraper", True),
        (" pep-scraper ", True),
        ("nicht pep-scraper", False),
        ("", False),
    ],
)
def test_marker_matches_exactly(note: str, ours: bool) -> None:
    assert ExistingOverride(date(2026, 11, 1), None, note).is_ours is ours
