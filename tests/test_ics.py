from datetime import date, datetime
from typing import Any

import pytest
from icalendar import Calendar

from pep_scraper.ics import build_calendar
from pep_scraper.models import RosterEvent

NIGHT = RosterEvent(
    uid="a@pep",
    summary="N003 21:45-06:15",
    description="Station 1",
    start=datetime(2026, 11, 1, 21, 45),
    end=datetime(2026, 11, 2, 6, 15),
    all_day=False,
)
VACATION = RosterEvent(
    uid="b@pep",
    summary="Urlaub",
    description="",
    start=date(2026, 11, 1),
    end=date(2026, 11, 2),
    all_day=True,
)


def _parse(raw: bytes) -> Any:  # icalendar's property types are a wide union
    return Calendar.from_ical(raw)


def test_calendar_contains_events() -> None:
    cal = _parse(build_calendar((NIGHT, VACATION), tz_name="Europe/Berlin"))
    vevents = cal.walk("VEVENT")
    assert [str(v["SUMMARY"]) for v in vevents] == [NIGHT.summary, VACATION.summary]
    assert [str(v["UID"]) for v in vevents] == ["a@pep", "b@pep"]


def test_timed_event_has_timezone() -> None:
    cal = _parse(build_calendar((NIGHT,), tz_name="Europe/Berlin"))
    dtstart = cal.walk("VEVENT")[0]["DTSTART"].dt
    assert dtstart.tzinfo is not None
    assert dtstart.utcoffset().total_seconds() == 3600  # CET in November
    assert dtstart.hour == 21


def test_all_day_event_uses_date() -> None:
    cal = _parse(build_calendar((VACATION,), tz_name="Europe/Berlin"))
    vevent = cal.walk("VEVENT")[0]
    assert vevent["DTSTART"].dt == date(2026, 11, 1)
    assert vevent["DTEND"].dt == date(2026, 11, 2)


def test_calendar_has_name_and_vtimezone() -> None:
    cal = _parse(build_calendar((NIGHT,), tz_name="Europe/Berlin"))
    assert str(cal["X-WR-CALNAME"]) == "Dienstplan PEP"
    assert cal.walk("VTIMEZONE")


def test_empty_calendar_is_valid() -> None:
    cal = _parse(build_calendar((), tz_name="Europe/Berlin"))
    assert cal.walk("VEVENT") == []


def test_timed_event_with_date_rejected() -> None:
    bad = RosterEvent("c@pep", "x", "", date(2026, 11, 1), date(2026, 11, 2), False)
    with pytest.raises(TypeError, match="datetime"):
        build_calendar((bad,), tz_name="Europe/Berlin")
