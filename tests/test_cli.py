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
