from datetime import date, datetime
from typing import Any

import pytest

from pep_scraper.models import RosterEvent
from pep_scraper.parser import ParseError, parse_dashboard


def _by_summary(events: tuple[RosterEvent, ...], summary: str) -> RosterEvent:
    return next(e for e in events if e.summary == summary)


def test_parses_all_known_entries(dashboard_json: dict[str, Any]) -> None:
    events = parse_dashboard(dashboard_json)
    # 6 raw entries, 1 unknown type skipped
    assert len(events) == 5


def test_absence_is_all_day(dashboard_json: dict[str, Any]) -> None:
    ev = _by_summary(parse_dashboard(dashboard_json), "Urlaub")
    assert ev.all_day is True
    assert ev.start == date(2026, 11, 1)
    assert ev.end == date(2026, 11, 2)


def test_night_shift_ends_next_day(dashboard_json: dict[str, Any]) -> None:
    ev = _by_summary(parse_dashboard(dashboard_json), "N003 21:45-06:15")
    assert ev.all_day is False
    assert ev.start == datetime(2026, 11, 1, 21, 45)
    assert ev.end == datetime(2026, 11, 2, 6, 15)
    assert "Station 1" in ev.description


def test_day_shift_same_day(dashboard_json: dict[str, Any]) -> None:
    ev = _by_summary(parse_dashboard(dashboard_json), "S001 13:45-22:15")
    assert ev.start == datetime(2026, 11, 5, 13, 45)
    assert ev.end == datetime(2026, 11, 5, 22, 15)


def test_zero_length_shift_becomes_all_day(dashboard_json: dict[str, Any]) -> None:
    ev = _by_summary(
        parse_dashboard(dashboard_json), "FREI Freier Tag, Bewertung nach Freigabe"
    )
    assert ev.all_day is True
    assert ev.start == date(2026, 11, 3)
    assert ev.end == date(2026, 11, 4)


def test_uids_are_unique_and_stable(dashboard_json: dict[str, Any]) -> None:
    first = parse_dashboard(dashboard_json)
    second = parse_dashboard(dashboard_json)
    assert [e.uid for e in first] == [e.uid for e in second]
    assert len({e.uid for e in first}) == len(first)


def test_input_is_not_mutated(dashboard_json: dict[str, Any]) -> None:
    import copy

    before = copy.deepcopy(dashboard_json)
    parse_dashboard(dashboard_json)
    assert dashboard_json == before


def test_empty_events() -> None:
    assert parse_dashboard({"events": []}) == ()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"events": "nope"},
        {"events": [{"absence": True}]},
        {"events": [{"type": "SPEP_PLAN", "date": "2026-11-01", "shifts": [{}]}]},
    ],
)
def test_malformed_payload_raises(payload: dict[str, Any]) -> None:
    with pytest.raises(ParseError):
        parse_dashboard(payload)


def test_event_kinds_codes_and_colors(dashboard_json: dict[str, Any]) -> None:
    events = {e.summary: e for e in parse_dashboard(dashboard_json)}
    assert (events["Urlaub"].kind, events["Urlaub"].code) == ("absence", "Urlaub")
    night = events["N003 21:45-06:15"]
    assert (night.kind, night.code) == ("shift", "N003")
    # LOGA colours are Windows COLORREF (0x00BBGGRR): 16757675 -> #ABB3FF
    assert night.color == "#ABB3FF"
    free = events["FREI Freier Tag, Bewertung nach Freigabe"]
    assert (free.kind, free.code) == ("free", "FREI")
    assert events["Urlaub"].color is None
