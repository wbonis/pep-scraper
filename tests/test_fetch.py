import time
from pathlib import Path
from typing import Any

import pytest

from pep_scraper.config import Config
from pep_scraper.fetch import (
    CaptchaRequiredError,
    FetchError,
    LoginError,
    MaintenanceError,
    PasswordExpiredError,
    TwoFactorRequiredError,
    fetch_dashboard,
)

from .fake_loga import APP_PATH, FakeOptions, serve

pytestmark = pytest.mark.browser


def _cfg(
    base_url: str, password: str = "s3cret", cache_dir: Path | None = None
) -> Config:
    return Config(
        username="alice",
        password=password,
        base_url=base_url,
        output=Path("unused.ics"),
        headless=True,
        timeout_ms=5_000,
        tz_name="Europe/Berlin",
        cache_dir=cache_dir,
    )


def test_fetch_returns_shift_json(dashboard_json: dict[str, Any]) -> None:
    with serve(FakeOptions(payload=dashboard_json)) as url:
        assert fetch_dashboard(_cfg(url)) == dashboard_json


def test_wrong_password_fails_fast_with_loga_text(
    dashboard_json: dict[str, Any],
) -> None:
    started = time.monotonic()
    with (
        serve(FakeOptions(payload=dashboard_json)) as url,
        pytest.raises(LoginError, match="Kennwort ist falsch"),
    ):
        fetch_dashboard(_cfg(url, password="wrong"))
    assert time.monotonic() - started < 4  # no waiting for the 5 s timeout


def test_maintenance_lock_is_not_a_login_error(dashboard_json: dict[str, Any]) -> None:
    with (
        serve(FakeOptions(payload=dashboard_json, maintenance=True)) as url,
        pytest.raises(MaintenanceError, match="Wartungsarbeiten"),
    ):
        fetch_dashboard(_cfg(url))


def test_password_change_prompt_raises(dashboard_json: dict[str, Any]) -> None:
    with (
        serve(FakeOptions(payload=dashboard_json, password_expired=True)) as url,
        pytest.raises(PasswordExpiredError),
    ):
        fetch_dashboard(_cfg(url))


def test_visible_captcha_raises(dashboard_json: dict[str, Any]) -> None:
    with (
        serve(FakeOptions(payload=dashboard_json, captcha_visible=True)) as url,
        pytest.raises(CaptchaRequiredError),
    ):
        fetch_dashboard(_cfg(url))


def test_visible_2fa_raises(dashboard_json: dict[str, Any]) -> None:
    with (
        serve(FakeOptions(payload=dashboard_json, twofa_visible=True)) as url,
        pytest.raises(TwoFactorRequiredError),
    ):
        fetch_dashboard(_cfg(url))


def test_http_error_raises_fetch_error(dashboard_json: dict[str, Any]) -> None:
    with (
        serve(FakeOptions(payload=dashboard_json, shift_status=500)) as url,
        pytest.raises(FetchError, match="500"),
    ):
        fetch_dashboard(_cfg(url))


def test_unreachable_host_raises_fetch_error() -> None:
    with pytest.raises(FetchError):
        fetch_dashboard(_cfg("http://127.0.0.1:9"))


def test_second_run_loads_app_from_cache(
    dashboard_json: dict[str, Any], tmp_path: Path
) -> None:
    opts = FakeOptions(payload=dashboard_json)
    with serve(opts) as url:
        assert fetch_dashboard(_cfg(url, cache_dir=tmp_path / "c")) == dashboard_json
        assert fetch_dashboard(_cfg(url, cache_dir=tmp_path / "c")) == dashboard_json
    assert opts.hits.count(APP_PATH) == 1
    assert opts.hits.count("/loga3/") == 2  # login page itself is never cached
    assert opts.login_cookies == ["", ""]  # no session survives between runs
    root = tmp_path / "c"
    assert root.stat().st_mode & 0o777 == 0o700
    default = root / "chromium" / "Default"
    assert {p.name for p in default.iterdir()} <= {"Cache", "Code Cache"}
    assert [p.name for p in (root / "chromium").iterdir()] == ["Default"]


def test_without_cache_dir_every_run_downloads(
    dashboard_json: dict[str, Any],
) -> None:
    opts = FakeOptions(payload=dashboard_json)
    with serve(opts) as url:
        fetch_dashboard(_cfg(url))
        fetch_dashboard(_cfg(url))
    assert opts.hits.count(APP_PATH) == 2


def test_unsafe_cache_dir_is_ignored(
    dashboard_json: dict[str, Any], tmp_path: Path
) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o777)  # anyone could swap the cache dir
    opts = FakeOptions(payload=dashboard_json)
    with serve(opts) as url:
        assert fetch_dashboard(_cfg(url, cache_dir=shared / "c")) == dashboard_json
        assert fetch_dashboard(_cfg(url, cache_dir=shared / "c")) == dashboard_json
    assert opts.hits.count(APP_PATH) == 2  # no cache used
