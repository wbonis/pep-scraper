from datetime import time, timedelta
from pathlib import Path

import pytest

from pep_scraper.naming import NamesError, load_names
from pep_scraper.settings import (
    DEFAULT_HOLIDAYS,
    BreakRule,
    Credit,
    Settings,
    load_settings,
)


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "schichten.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    assert load_settings(tmp_path / "nope.toml") == Settings()


def test_defaults() -> None:
    s = Settings()
    assert s.holiday_rule is True
    assert s.holiday_titles == DEFAULT_HOLIDAYS
    assert s.add_new_codes is True
    assert s.credit == Credit(frozenset(), "termin", time(8, 0), timedelta(hours=8))
    assert s.pause == BreakRule(0, timedelta(0), "kuerzen")


def test_file_without_section_gives_defaults(tmp_path: Path) -> None:
    path = _write(tmp_path, '[S006]\nname = "Spätdienst"\n')
    assert load_settings(path) == Settings()


def test_full_section(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "[einstellungen]\n"
        "feiertagsregel = false\n"
        'feiertage = ["Feiertag"]\n'
        "neue_codes_eintragen = false\n"
        'gutschrift = ["Urlaub", "Fortbildung"]\n'
        'gutschrift_modus = "info"\n'
        'schicht_start = "07:30"\n'
        "stunden_pro_tag = 7.7\n"
        "pause_minuten = 30\n"
        "pause_ab_stunden = 6\n"
        'pause_modus = "info"\n',
    )
    assert load_settings(path) == Settings(
        holiday_rule=False,
        holiday_titles=frozenset({"feiertag"}),
        add_new_codes=False,
        credit=Credit(
            frozenset({"urlaub", "fortbildung"}),
            "info",
            time(7, 30),
            timedelta(hours=7.7),
        ),
        pause=BreakRule(30, timedelta(hours=6), "info"),
    )


def test_hours_per_week_is_five_days(tmp_path: Path) -> None:
    path = _write(tmp_path, "[einstellungen]\nstunden_pro_woche = 39\n")
    assert load_settings(path).credit.hours == timedelta(hours=7.8)


@pytest.mark.parametrize(
    "body",
    [
        "feiertagsregel = 1",
        "feiertage = 'Feiertag'",
        "feiertage = [1]",
        "gutschrift_modus = 'nein'",
        "schicht_start = '25:00'",
        "schicht_start = 8",
        "stunden_pro_tag = 0",
        "stunden_pro_tag = 25",
        "stunden_pro_tag = true",
        "stunden_pro_tag = 8\nstunden_pro_woche = 40",
        "pause_minuten = -5",
        "pause_minuten = 7.5",
        "pause_ab_stunden = -1",
        "pause_modus = 'weg'",
        "stunden_pro_tag = " + "9" * 400,
        "pause_ab_stunden = 1e300",
        "pause_ab_stunden = 25",
        "pause_minuten = 10000000000000",
        "pause_minuten = 1441",
        "unbekannt = 1",
    ],
)
def test_invalid_section_raises(tmp_path: Path, body: str) -> None:
    path = _write(tmp_path, f"[einstellungen]\n{body}\n")
    with pytest.raises(NamesError, match="einstellungen"):
        load_settings(path)


def test_section_is_not_a_name(tmp_path: Path) -> None:
    path = _write(
        tmp_path, '[einstellungen]\npause_minuten = 30\n\n[S006]\nname = "Spät"\n'
    )
    assert set(load_names(path)) == {"S006"}
