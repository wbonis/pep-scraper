from datetime import date, datetime
from pathlib import Path

from pep_scraper.models import RosterEvent
from pep_scraper.naming import NameEntry, load_names
from pep_scraper.new_codes import append_codes, unknown_codes


def _shift(code: str, summary: str = "") -> RosterEvent:
    return RosterEvent(
        uid=code,
        summary=summary or f"{code} 13:45-22:15",
        description="Station 1",
        start=datetime(2026, 11, 5, 13, 45),
        end=datetime(2026, 11, 5, 22, 15),
        all_day=False,
        kind="shift",
        code=code,
    )


def _free(code: str) -> RosterEvent:
    return RosterEvent(
        uid=code,
        summary=f"{code} Freier Tag",
        description="",
        start=date(2026, 11, 3),
        end=date(2026, 11, 4),
        all_day=True,
        kind="free",
        code=code,
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


def test_unknown_codes_skip_known_absences_and_duplicates() -> None:
    events = (
        _shift("S006"),
        _shift("ZD015"),
        _shift("ZD015"),
        _free("FREI"),
        _absence("Urlaub"),
    )
    names = {"S006": NameEntry("Spät")}
    assert unknown_codes(events, names) == (
        ("ZD015", NameEntry("ZD015 13:45-22:15")),
        ("FREI", NameEntry("FREI Freier Tag")),
    )


def test_unknown_code_uses_heuristic_name() -> None:
    assert unknown_codes((_shift("N003"),), {}) == (
        ("N003", NameEntry("Nachtdienst", "moon")),
    )


def test_reserved_and_empty_codes_skipped() -> None:
    assert unknown_codes((_shift("einstellungen"), _shift("")), {}) == ()


def test_long_or_odd_name_is_cleaned() -> None:
    ((_, entry),) = unknown_codes((_shift("X1", "X1 " + "a" * 200 + "\t"),), {})
    assert len(entry.name) == 100 and entry.name.isprintable()


def test_append_keeps_content_and_is_loadable(tmp_path: Path) -> None:
    path = tmp_path / "schichten.toml"
    original = '# meine Datei\n[S006]\nname = "Spät"'  # no trailing newline
    path.write_text(original, encoding="utf-8")
    append_codes(
        path,
        (
            ("ZD015", NameEntry("ZD015 11:30-20:00")),
            ("A B", NameEntry('Sonder "x" \\ y', "moon")),
        ),
        today=date(2026, 11, 2),
    )
    text = path.read_text(encoding="utf-8")
    assert text.startswith(original + "\n")
    assert "# automatisch eingetragen am 2026-11-02" in text
    assert load_names(path) == {
        "S006": NameEntry("Spät"),
        "ZD015": NameEntry("ZD015 11:30-20:00"),
        "A B": NameEntry('Sonder "x" \\ y', "moon"),
    }


def test_append_creates_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "schichten.toml"
    append_codes(path, (("ZD015", NameEntry("Z")),), today=date(2026, 11, 2))
    assert load_names(path) == {"ZD015": NameEntry("Z")}


def test_append_nothing_leaves_file_alone(tmp_path: Path) -> None:
    path = tmp_path / "schichten.toml"
    append_codes(path, (), today=date(2026, 11, 2))
    assert not path.exists()


def test_non_printable_and_surrogate_codes_skipped() -> None:
    events = (_shift("A\x7fB"), _shift("\ud800"), _shift("A\nB"), _shift("OK1"))
    assert [code for code, _ in unknown_codes(events, {})] == ["OK1"]


def test_code_equal_to_absence_title_or_health_skipped() -> None:
    events = (_free("K"), _absence("K"), _shift("Krank"), _shift("OK1"))
    assert [code for code, _ in unknown_codes(events, {})] == ["OK1"]


def test_append_skips_codes_added_meanwhile(tmp_path: Path) -> None:
    path = tmp_path / "schichten.toml"
    path.write_text('[F9]\nname = "von Hand"\n', encoding="utf-8")
    append_codes(path, (("F9", NameEntry("auto")),), today=date(2026, 11, 2))
    assert load_names(path) == {"F9": NameEntry("von Hand")}


def test_append_refuses_to_write_broken_toml(tmp_path: Path) -> None:
    import pytest

    path = tmp_path / "schichten.toml"
    path.write_text("[kaputt", encoding="utf-8")
    with pytest.raises(ValueError):
        append_codes(path, (("F9", NameEntry("x")),), today=date(2026, 11, 2))
    assert path.read_text(encoding="utf-8") == "[kaputt"


def test_append_keeps_symlink_and_mode(tmp_path: Path) -> None:
    target = tmp_path / "dotfiles" / "schichten.toml"
    target.parent.mkdir()
    target.write_text('[S1]\nname = "x"\n', encoding="utf-8")
    target.chmod(0o640)
    link = tmp_path / "schichten.toml"
    link.symlink_to(target)
    append_codes(link, (("F9", NameEntry("y")),), today=date(2026, 11, 2))
    assert link.is_symlink()
    assert target.stat().st_mode & 0o777 == 0o640
    assert set(load_names(target)) == {"S1", "F9"}
