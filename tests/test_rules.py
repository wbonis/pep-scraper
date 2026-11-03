from dataclasses import replace
from datetime import date, datetime, time, timedelta

import pytest

from pep_scraper.models import RosterEvent
from pep_scraper.rules import (
    FREE_DAY,
    apply_break,
    apply_credit,
    apply_holiday_rule,
    apply_rules,
)
from pep_scraper.settings import DEFAULT_HOLIDAYS, BreakRule, Credit, Settings


def _shift(day: int, start: int = 13, end: int = 22, code: str = "S006") -> RosterEvent:
    begin = datetime(2026, 12, day, start)
    finish = datetime(2026, 12, day, end) + timedelta(days=1 if end < start else 0)
    return RosterEvent(
        uid=f"s{day}",
        summary=f"{code} {start:02d}:00-{end:02d}:00",
        description="Station 1",
        start=begin,
        end=finish,
        all_day=False,
        kind="shift",
        code=code,
    )


def _all_day(day: int, title: str, kind: str = "absence") -> RosterEvent:
    return RosterEvent(
        uid=f"a{day}{title}",
        summary=title,
        description="Abwesenheit",
        start=date(2026, 12, day),
        end=date(2026, 12, day) + timedelta(days=1),
        all_day=True,
        kind=kind,  # type: ignore[arg-type]
        code=title,
    )


# --- Feiertagsregel ---------------------------------------------------------


def test_holiday_with_shift_is_dropped_shift_kept() -> None:
    shift = _shift(31)
    events = (_all_day(31, "Betrieblich freier Tag"), shift)
    assert apply_holiday_rule(events, DEFAULT_HOLIDAYS) == (shift,)


def test_holiday_with_free_shift_is_dropped() -> None:
    frei = _all_day(31, "FREI", kind="free")
    events = (_all_day(31, "Feiertag"), frei)
    assert apply_holiday_rule(events, DEFAULT_HOLIDAYS) == (frei,)


@pytest.mark.parametrize("title", ["Feiertag", "Feiertage", "betrieblich FREIER Tag"])
def test_holiday_without_shift_becomes_free_day(title: str) -> None:
    holiday = _all_day(25, title)
    (event,) = apply_holiday_rule((holiday,), DEFAULT_HOLIDAYS)
    assert event == replace(holiday, kind="free", summary=FREE_DAY, description=title)


def test_other_absence_on_shift_day_stays() -> None:
    events = (_all_day(31, "Krank mit EFZ"), _shift(31))
    assert apply_holiday_rule(events, DEFAULT_HOLIDAYS) == events


def test_shift_on_other_day_does_not_drop_holiday() -> None:
    free, shift = apply_holiday_rule(
        (_all_day(25, "Feiertag"), _shift(26)), DEFAULT_HOLIDAYS
    )
    assert free.kind == "free" and shift == _shift(26)


def test_night_shift_from_previous_day_does_not_count() -> None:
    night = _shift(24, start=21, end=6)
    _, free = apply_holiday_rule((night, _all_day(25, "Feiertag")), DEFAULT_HOLIDAYS)
    assert free.kind == "free"


def test_rule_off_keeps_everything() -> None:
    events = (_all_day(31, "Feiertag"), _shift(31), _all_day(25, "Feiertag"))
    settings = Settings(holiday_rule=False)
    assert apply_rules(events, settings) == events


# --- Arbeitszeitäquivalent ---------------------------------------------------

URLAUB = Credit(frozenset({"urlaub"}), "termin", time(8, 0), timedelta(hours=8))


def test_credit_termin_turns_all_day_into_timed() -> None:
    (event,) = apply_credit((_all_day(7, "Urlaub"),), URLAUB)
    assert (event.start, event.end, event.all_day, event.kind) == (
        datetime(2026, 12, 7, 8, 0),
        datetime(2026, 12, 7, 16, 0),
        False,
        "absence",
    )


def test_credit_custom_start_and_fraction() -> None:
    credit = replace(URLAUB, start=time(7, 30), hours=timedelta(hours=7.7))
    (event,) = apply_credit((_all_day(7, "Urlaub"),), credit)
    assert event.end == datetime(2026, 12, 7, 15, 12)


def test_credit_info_keeps_all_day() -> None:
    credit = replace(URLAUB, mode="info", hours=timedelta(hours=7.7))
    (event,) = apply_credit((_all_day(7, "Urlaub"),), credit)
    assert event.all_day is True
    assert event.description == "Abwesenheit\nGutschrift 7:42 Std."


def test_credit_ignores_unlisted_and_timed() -> None:
    events = (_all_day(7, "Krank mit EFZ"), replace(_shift(7), code="Urlaub"))
    assert apply_credit(events, URLAUB) == events


def test_credit_matches_case_insensitive() -> None:
    (event,) = apply_credit((_all_day(7, "URLAUB"),), URLAUB)
    assert event.all_day is False


def test_empty_credit_list_changes_nothing() -> None:
    events = (_all_day(7, "Urlaub"),)
    assert apply_credit(events, Credit()) == events


def test_holiday_free_day_can_be_credited() -> None:
    settings = Settings(credit=replace(URLAUB, titles=frozenset({"feiertag"})))
    (event,) = apply_rules((_all_day(25, "Feiertag"),), settings)
    assert (event.kind, event.summary, event.all_day) == ("free", FREE_DAY, False)


# --- Pause -------------------------------------------------------------------


def test_break_cuts_end_of_shift() -> None:
    (event,) = apply_break((_shift(5),), BreakRule(30, timedelta(0), "kuerzen"))
    assert event.end == datetime(2026, 12, 5, 21, 30)


def test_break_night_shift_ends_next_day() -> None:
    night = _shift(5, start=21, end=6)
    (event,) = apply_break((night,), BreakRule(30, timedelta(0), "kuerzen"))
    assert event.end == datetime(2026, 12, 6, 5, 30)


def test_break_only_above_threshold() -> None:
    short = _shift(5, start=8, end=14)  # exactly 6 h: no break due
    long = _shift(6, start=8, end=15)
    rule = BreakRule(30, timedelta(hours=6), "kuerzen")
    assert apply_break((short, long), rule) == (
        short,
        replace(long, end=datetime(2026, 12, 6, 14, 30)),
    )


def test_break_info_keeps_times() -> None:
    (event,) = apply_break((_shift(5),), BreakRule(30, timedelta(0), "info"))
    assert event.end == datetime(2026, 12, 5, 22, 0)
    assert event.description == "Station 1\nNetto 8:30 Std."


def test_break_skips_free_absence_and_credit() -> None:
    credited = apply_credit((_all_day(7, "Urlaub"),), URLAUB)
    events = (_all_day(3, "FREI", kind="free"), *credited)
    assert apply_break(events, BreakRule(30, timedelta(0), "kuerzen")) == events


def test_break_never_longer_than_shift() -> None:
    tiny = replace(_shift(5, start=8, end=8), end=datetime(2026, 12, 5, 8, 20))
    assert apply_break((tiny,), BreakRule(30, timedelta(0), "kuerzen")) == (tiny,)


def test_zero_break_changes_nothing() -> None:
    events = (_shift(5),)
    assert apply_break(events, BreakRule()) == events
