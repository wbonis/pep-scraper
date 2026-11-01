from pathlib import Path
from typing import Any

import pytest

from pep_scraper.config import Config
from pep_scraper.fetch import (
    CaptchaRequiredError,
    FetchError,
    LoginError,
    TwoFactorRequiredError,
    fetch_dashboard,
)

from .fake_loga import FakeOptions, serve

pytestmark = pytest.mark.browser


def _cfg(base_url: str, password: str = "s3cret") -> Config:
    return Config(
        username="alice",
        password=password,
        base_url=base_url,
        output=Path("unused.ics"),
        headless=True,
        timeout_ms=5_000,
        tz_name="Europe/Berlin",
    )


def test_fetch_returns_shift_json(dashboard_json: dict[str, Any]) -> None:
    with serve(FakeOptions(payload=dashboard_json)) as url:
        assert fetch_dashboard(_cfg(url)) == dashboard_json


def test_wrong_password_raises_login_error(dashboard_json: dict[str, Any]) -> None:
    with serve(FakeOptions(payload=dashboard_json)) as url, pytest.raises(LoginError):
        fetch_dashboard(_cfg(url, password="wrong"))


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
