from datetime import date
from pathlib import Path
from typing import Any

import pytest
from icalendar import Calendar

from pep_scraper import cli
from pep_scraper.config import Config
from pep_scraper.fetch import CaptchaRequiredError, FetchError


def _config(tmp_path: Path) -> Config:
    return Config(
        username="u",
        password="p",
        base_url="https://example.test",
        output=tmp_path / "out" / "dienstplan.ics",
        headless=True,
        timeout_ms=1000,
        tz_name="Europe/Berlin",
        names_file=tmp_path / "schichten.toml",
    )


def test_run_writes_ics(tmp_path: Path, dashboard_json: dict[str, Any]) -> None:
    cfg = _config(tmp_path)
    code = cli.run(cfg, fetcher=lambda _cfg: dashboard_json)
    assert code == 0
    cal = Calendar.from_ical(cfg.output.read_bytes())
    assert len(cal.walk("VEVENT")) == 5
    assert not list(cfg.output.parent.glob("*.tmp"))


def test_run_keeps_old_file_on_fetch_error(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cfg.output.parent.mkdir(parents=True)
    cfg.output.write_bytes(b"old")

    def boom(_cfg: Config) -> dict[str, Any]:
        raise FetchError("down")

    assert cli.run(cfg, fetcher=boom) == cli.EXIT_FETCH
    assert cfg.output.read_bytes() == b"old"


def test_run_captcha_exit_code(tmp_path: Path) -> None:
    def captcha(_cfg: Config) -> dict[str, Any]:
        raise CaptchaRequiredError("captcha")

    assert cli.run(_config(tmp_path), fetcher=captcha) == cli.EXIT_LOGIN


def test_run_parse_error_exit_code(tmp_path: Path) -> None:
    assert cli.run(_config(tmp_path), fetcher=lambda _c: {}) == cli.EXIT_PARSE


def test_main_missing_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PEP_USERNAME", raising=False)
    monkeypatch.delenv("PEP_PASSWORD", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here
    assert cli.main([]) == cli.EXIT_CONFIG


def test_main_uses_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dashboard_json: dict[str, Any]
) -> None:
    out = tmp_path / "x.ics"
    (tmp_path / ".env").write_text(
        f"PEP_USERNAME=u\nPEP_PASSWORD=p\nPEP_BASE_URL=https://example.pi-asp.de\n"
        f"PEP_OUTPUT={out}\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("PEP_USERNAME", raising=False)
    monkeypatch.delenv("PEP_PASSWORD", raising=False)
    monkeypatch.delenv("PEP_OUTPUT", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "fetch_dashboard", lambda _cfg: dashboard_json)
    assert cli.main([]) == 0
    assert out.exists()


def test_output_is_private(tmp_path: Path, dashboard_json: dict[str, Any]) -> None:
    cfg = _config(tmp_path)
    cli.run(cfg, fetcher=lambda _cfg: dashboard_json)
    assert cfg.output.stat().st_mode & 0o777 == 0o600
    assert [p.name for p in cfg.output.parent.iterdir()] == [cfg.output.name]


def _yuvomi_cfg(tmp_path: Path) -> Config:
    from dataclasses import replace

    from pep_scraper.config import YuvomiConfig
    from pep_scraper.yuvomi_plan import AbsenceMode

    yuv = YuvomiConfig(
        "https://y.example", "k", 4, AbsenceMode.NEUTRAL, tmp_path / "state.json"
    )
    return replace(_config(tmp_path), yuvomi=yuv)


def test_run_syncs_yuvomi(tmp_path: Path, dashboard_json: dict[str, Any]) -> None:
    from contextlib import nullcontext

    from .test_yuvomi_sync import FakeClient

    fake = FakeClient()
    code = cli.run(
        _yuvomi_cfg(tmp_path),
        fetcher=lambda _c: dashboard_json,
        client_factory=lambda _y: nullcontext(fake),
    )
    assert code == 0
    assert any(c[0] == "put" and c[1] == 4 for c in fake.calls)


def test_run_yuvomi_error_exit_code(
    tmp_path: Path, dashboard_json: dict[str, Any]
) -> None:
    from contextlib import nullcontext

    from pep_scraper.yuvomi_client import YuvomiError

    from .test_yuvomi_sync import FakeClient

    class Broken(FakeClient):
        def list_overrides(self, *_a: Any) -> Any:
            raise YuvomiError("HTTP 403")

    cfg = _yuvomi_cfg(tmp_path)
    code = cli.run(
        cfg,
        fetcher=lambda _c: dashboard_json,
        client_factory=lambda _y: nullcontext(Broken()),
    )
    assert code == cli.EXIT_YUVOMI
    assert cfg.output.exists()  # ICS still written


def test_dry_run_flag_parsed() -> None:
    assert cli._parse_args(["--dry-run"]).dry_run is True


def test_run_password_expired_exit_code(tmp_path: Path) -> None:
    from pep_scraper.fetch import PasswordExpiredError

    def expired(_cfg: Config) -> dict[str, Any]:
        raise PasswordExpiredError("neues Kennwort")

    assert cli.run(_config(tmp_path), fetcher=expired) == cli.EXIT_PASSWORD == 6


def test_run_maintenance_is_fetch_error(tmp_path: Path) -> None:
    from pep_scraper.fetch import MaintenanceError

    def locked(_cfg: Config) -> dict[str, Any]:
        raise MaintenanceError("Wartung")

    assert cli.run(_config(tmp_path), fetcher=locked) == cli.EXIT_FETCH


def test_run_persists_created_type_ids(
    tmp_path: Path, dashboard_json: dict[str, Any]
) -> None:
    from contextlib import nullcontext
    from dataclasses import replace

    from pep_scraper.state import load_tracked_types

    from .test_yuvomi_sync import FakeClient

    cfg = _yuvomi_cfg(tmp_path)
    assert cfg.yuvomi is not None
    state = tmp_path / "state.json"
    cfg = replace(cfg, yuvomi=replace(cfg.yuvomi, state_file=state))
    cli.run(
        cfg,
        fetcher=lambda _c: dashboard_json,
        client_factory=lambda _y: nullcontext(FakeClient()),
    )
    assert load_tracked_types(state, "https://y.example")  # created types remembered


def test_names_applied_to_ics(tmp_path: Path, dashboard_json: dict[str, Any]) -> None:
    from dataclasses import replace

    names = tmp_path / "schichten.toml"
    names.write_text('[S001]\nname = "Spätdienst"\nicon = "sunset"\n', encoding="utf-8")
    cfg = replace(_config(tmp_path), names_file=names)
    assert cli.run(cfg, fetcher=lambda _c: dashboard_json) == 0
    summaries = {
        str(e["SUMMARY"])
        for e in Calendar.from_ical(cfg.output.read_bytes()).walk("VEVENT")
    }
    assert (
        "Spätdienst" in summaries and "Nachtdienst" in summaries
    )  # file + rule of thumb


def test_invalid_names_file_is_config_error(tmp_path: Path) -> None:
    from dataclasses import replace

    names = tmp_path / "schichten.toml"
    names.write_text("[kaputt", encoding="utf-8")
    cfg = replace(_config(tmp_path), names_file=names)
    called: list[bool] = []

    def fetcher(_c: Config) -> dict[str, Any]:
        called.append(True)
        return {}

    assert cli.run(cfg, fetcher=fetcher) == cli.EXIT_CONFIG
    assert not called  # fails before logging in to LOGA


def test_write_failure_leaves_no_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from pep_scraper.files import write_private_atomic

    def boom(_fd: int) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "fsync", boom)
    with pytest.raises(OSError):
        write_private_atomic(tmp_path / "x.ics", b"data")
    assert list(tmp_path.iterdir()) == []


HOLIDAY_AND_SHIFT = {
    "events": [
        {
            "title": "Betrieblich freier Tag",
            "date": "2026-12-31",
            "absence": True,
            "noon": False,
            "afternoon": False,
        },
        {
            "title": "Abteilung A → Station 1",
            "date": "2026-12-31",
            "absence": False,
            "type": "SPEP_PLAN",
            "shifts": [
                {
                    "from": "2026-12-31T13:45:00",
                    "to": "2026-12-31T22:15:00",
                    "code": "S006",
                    "name": "13:45-22:15",
                    "color": 10420139,
                }
            ],
        },
        {"title": "Feiertag", "date": "2026-12-25", "absence": True},
    ]
}


def _summaries(cfg: Config) -> dict[str, str]:
    cal = Calendar.from_ical(cfg.output.read_bytes())
    return {
        str(e["SUMMARY"]): e.decoded("DTSTART").isoformat() for e in cal.walk("VEVENT")
    }


def test_holiday_rule_keeps_shift_and_frees_holiday(tmp_path: Path) -> None:
    from contextlib import nullcontext

    from .test_yuvomi_sync import FakeClient

    fake = FakeClient()
    cfg = _yuvomi_cfg(tmp_path)
    code = cli.run(
        cfg,
        fetcher=lambda _c: HOLIDAY_AND_SHIFT,
        client_factory=lambda _y: nullcontext(fake),
    )
    assert code == 0
    assert _summaries(cfg) == {
        "Spätdienst": "2026-12-31T13:45:00+01:00",
        "Freier Tag": "2026-12-25",
    }
    puts = {c[2]: c[3] for c in fake.calls if c[0] == "put"}
    assert ("create", "S006") in fake.calls
    assert ("create", None) not in fake.calls  # no absence type
    assert puts[date(2026, 12, 31)] is not None  # the shift, not the holiday
    assert puts[date(2026, 12, 25)] is None  # explicit day off


def test_settings_from_names_file(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cfg.names_file.write_text(
        "[einstellungen]\nfeiertagsregel = false\npause_minuten = 30\n",
        encoding="utf-8",
    )
    assert cli.run(cfg, fetcher=lambda _c: HOLIDAY_AND_SHIFT) == 0
    cal = Calendar.from_ical(cfg.output.read_bytes())
    ends = {str(e["SUMMARY"]): e.decoded("DTEND") for e in cal.walk("VEVENT")}
    assert ends["Spätdienst"].strftime("%H:%M") == "21:45"
    assert "Betrieblich freier Tag" in ends and "Feiertag" in ends


def test_invalid_settings_is_config_error(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cfg.names_file.write_text("[einstellungen]\npause_minuten = -1\n", "utf-8")
    assert cli.run(cfg, fetcher=lambda _c: HOLIDAY_AND_SHIFT) == cli.EXIT_CONFIG


def test_unknown_codes_appended_once(
    tmp_path: Path, dashboard_json: dict[str, Any]
) -> None:
    from pep_scraper.naming import load_names

    cfg = _config(tmp_path)
    cfg.names_file.write_text('[S001]\nname = "Spät"\n', encoding="utf-8")
    cli.run(cfg, fetcher=lambda _c: dashboard_json)
    first = cfg.names_file.read_text(encoding="utf-8")
    assert set(load_names(cfg.names_file)) == {"S001", "N003", "FREI"}
    cli.run(cfg, fetcher=lambda _c: dashboard_json)
    assert cfg.names_file.read_text(encoding="utf-8") == first


def test_unknown_codes_not_appended_when_off_or_dry_run(
    tmp_path: Path, dashboard_json: dict[str, Any]
) -> None:
    cfg = _config(tmp_path)
    off = "[einstellungen]\nneue_codes_eintragen = false\n"
    cfg.names_file.write_text(off, encoding="utf-8")
    cli.run(cfg, fetcher=lambda _c: dashboard_json)
    assert cfg.names_file.read_text(encoding="utf-8") == off
    cfg.names_file.unlink()
    cli.run(cfg, fetcher=lambda _c: dashboard_json, dry_run=True)
    assert not cfg.names_file.exists()


def test_new_code_write_error_does_not_stop_run(
    tmp_path: Path, dashboard_json: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: Any, **_k: Any) -> None:
        raise ValueError("kaputt")

    monkeypatch.setattr(cli, "append_codes", boom)
    cfg = _config(tmp_path)
    assert cli.run(cfg, fetcher=lambda _c: dashboard_json) == 0
    assert cfg.output.exists()


def _env_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    out = tmp_path / "x.ics"
    (tmp_path / ".env").write_text(
        "PEP_USERNAME=u\nPEP_PASSWORD=p\nPEP_BASE_URL=https://example.pi-asp.de\n"
        f"PEP_OUTPUT={out}\nPEP_CACHE_DIR=off\n",
        encoding="utf-8",
    )
    for key in ("PEP_USERNAME", "PEP_PASSWORD", "PEP_OUTPUT", "YUVOMI_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    return out


def test_save_json_then_replay_without_loga(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dashboard_json: dict[str, Any]
) -> None:
    import json

    out = _env_dir(tmp_path, monkeypatch)
    saved = tmp_path / "loga.json"
    monkeypatch.setattr(cli, "fetch_dashboard", lambda _cfg: dashboard_json)
    assert cli.main(["--save-json", str(saved)]) == 0
    assert json.loads(saved.read_text(encoding="utf-8")) == dashboard_json
    assert saved.stat().st_mode & 0o777 == 0o600

    def no_loga(_cfg: Config) -> dict[str, Any]:
        raise AssertionError("LOGA must not be contacted")

    monkeypatch.setattr(cli, "fetch_dashboard", no_loga)
    out.unlink()
    assert cli.main(["--from-json", str(saved)]) == 0
    assert out.exists()


def test_save_json_not_written_on_fetch_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _env_dir(tmp_path, monkeypatch)
    saved = tmp_path / "loga.json"

    def down(_cfg: Config) -> dict[str, Any]:
        raise FetchError("down")

    monkeypatch.setattr(cli, "fetch_dashboard", down)
    assert cli.main(["--save-json", str(saved)]) == cli.EXIT_FETCH
    assert not saved.exists()


@pytest.mark.parametrize("content", [None, "kein json", "[1, 2]"])
def test_from_json_bad_file_is_fetch_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: str | None
) -> None:
    _env_dir(tmp_path, monkeypatch)
    path = tmp_path / "loga.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    assert cli.main(["--from-json", str(path)]) == cli.EXIT_FETCH


def test_from_and_save_json_exclusive() -> None:
    with pytest.raises(SystemExit):
        cli._parse_args(["--from-json", "a", "--save-json", "b"])


def test_save_json_write_error_does_not_stop_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dashboard_json: dict[str, Any]
) -> None:
    out = _env_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "fetch_dashboard", lambda _cfg: dashboard_json)
    target = tmp_path / "is_a_dir"
    target.mkdir()
    assert cli.main(["--save-json", str(target)]) == 0
    assert out.exists()


def test_from_json_warns_when_old_and_not_dry_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    dashboard_json: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    import json
    import os

    _env_dir(tmp_path, monkeypatch)
    saved = tmp_path / "loga.json"
    saved.write_text(json.dumps(dashboard_json), encoding="utf-8")
    two_days_ago = saved.stat().st_mtime - 2 * 86400
    os.utime(saved, (two_days_ago, two_days_ago))
    cli.main(["--from-json", str(saved), "--dry-run"])
    assert "Stunden alt" not in caplog.text
    cli.main(["--from-json", str(saved)])
    assert "48 Stunden alt" in caplog.text
