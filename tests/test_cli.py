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
        f"PEP_USERNAME=u\nPEP_PASSWORD=p\nPEP_OUTPUT={out}\n", encoding="utf-8"
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
