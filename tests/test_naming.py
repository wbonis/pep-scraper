from datetime import date, datetime
from pathlib import Path

import pytest

from pep_scraper.models import RosterEvent
from pep_scraper.naming import (
    NameEntry,
    NamesError,
    apply_names,
    is_health_reason,
    is_shown_absence,
    load_names,
)


def _shift(code: str) -> RosterEvent:
    return RosterEvent(
        uid=code,
        summary=f"{code} 13:45-22:15",
        description="Station 1",
        start=datetime(2026, 11, 5, 13, 45),
        end=datetime(2026, 11, 5, 22, 15),
        all_day=False,
        kind="shift",
        code=code,
        color="#ABB3FF",
    )


def _absence(title: str) -> RosterEvent:
    return RosterEvent(
        uid=title,
        summary=title,
        description="Abwesenheit",
        start=date(2026, 11, 16),
        end=date(2026, 11, 17),
        all_day=True,
        kind="absence",
        code=title,
    )


def test_load_names(tmp_path: Path) -> None:
    path = tmp_path / "schichten.toml"
    path.write_text(
        '[ZD015]\nname = "Früher Spätdienst"\nicon = "sunset"\n\n'
        '["Fachweiterbildung"]\nname = "Schule"\n',
        encoding="utf-8",
    )
    assert load_names(path) == {
        "ZD015": NameEntry("Früher Spätdienst", "sunset"),
        "Fachweiterbildung": NameEntry("Schule", None),
    }


def test_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_names(tmp_path / "nope.toml") == {}


@pytest.mark.parametrize(
    "content",
    [
        "[x",
        '[A]\nicon = "moon"\n',
        "[A]\nname = 3\n",
        '[A]\nname = "x"\nicon = "Bad Icon"\n',
    ],
)
def test_invalid_file_raises(tmp_path: Path, content: str) -> None:
    path = tmp_path / "schichten.toml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(NamesError):
        load_names(path)


def test_file_entry_wins() -> None:
    names = {"S006": NameEntry("Später Dienst", "clock")}
    (ev,) = apply_names((_shift("S006"),), names)
    assert (ev.summary, ev.icon, ev.code) == ("Später Dienst", "clock", "S006")


@pytest.mark.parametrize(
    ("code", "name", "icon"),
    [
        ("F013", "Frühdienst", "sunrise"),
        ("S006", "Spätdienst", "sunset"),
        ("N003", "Nachtdienst", "moon"),
    ],
)
def test_heuristic_for_unmapped_shift(code: str, name: str, icon: str) -> None:
    (ev,) = apply_names((_shift(code),), {})
    assert (ev.summary, ev.icon) == (name, icon)


def test_unknown_code_keeps_summary() -> None:
    (ev,) = apply_names((_shift("ZD015"),), {})
    assert ev.summary == "ZD015 13:45-22:15" and ev.icon is None


def test_absence_title_mapped_and_original_kept_in_code() -> None:
    names = {"Fachweiterbildung": NameEntry("Schule", "school")}
    (ev,) = apply_names((_absence("Fachweiterbildung"),), names)
    assert (ev.summary, ev.icon, ev.code) == ("Schule", "school", "Fachweiterbildung")


def test_unmapped_absence_unchanged() -> None:
    event = _absence("Urlaub")
    assert apply_names((event,), {}) == (event,)


@pytest.mark.parametrize(
    ("title", "health"),
    [
        ("Krank mit EFZ", True),
        ("Kind krank", True),
        ("AU", True),
        ("Reha", True),
        ("Kur", True),
        ("Arbeitsunfähig", True),
        ("Urlaub", False),
        ("Fortbildung", False),
        ("Fachweiterbildung", False),
        ("Kurs Hygiene", False),
        ("Feiertag", False),
    ],
)
def test_is_health_reason(title: str, health: bool) -> None:
    assert is_health_reason(title) is health


def test_non_utf8_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "schichten.toml"
    path.write_bytes(b'[A]\nname = "\xff"\n')
    with pytest.raises(NamesError):
        load_names(path)


@pytest.mark.parametrize(
    ("title", "named", "shown"),
    [
        ("Urlaub", (), True),
        ("Fachweiterbildung", (), True),
        ("Betrieblich freier Tag", (), True),
        ("Sonderurlaub Umzug", (), False),  # unknown -> hidden (fail closed)
        ("Sonderurlaub Umzug", ("Sonderurlaub Umzug",), True),  # named on purpose
        ("Krank mit EFZ", ("Krank mit EFZ",), False),  # health always hidden
    ],
)
def test_is_shown_absence(title: str, named: tuple[str, ...], shown: bool) -> None:
    assert is_shown_absence(title, frozenset(named)) is shown
