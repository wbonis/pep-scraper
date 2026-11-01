"""Log in to LOGA3 with a headless browser and capture the PEP shift JSON.

The dashboard's own JS requests ``pep/loadShiftsDashboard`` (incl. xsrf token)
after login; we only listen for that response instead of re-implementing
the GWT session/xsrf handling.
"""

import json
import logging
import time
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, Response, sync_playwright

from .config import Config

log = logging.getLogger(__name__)

SHIFT_ENDPOINT = "/api/dashboard/pep/loadShiftsDashboard"
LOGIN_PATH = "/loga3/"
POLL_MS = 250


class FetchError(RuntimeError):
    """Roster could not be retrieved."""


class LoginError(FetchError):
    """Login did not succeed."""


class CaptchaRequiredError(LoginError):
    """Server shows a captcha; manual login needed."""


class TwoFactorRequiredError(LoginError):
    """Server asks for a 2FA token."""


CHALLENGES: tuple[tuple[str, type[LoginError]], ...] = (
    ("#captchaInput", CaptchaRequiredError),
    ("#twofatoken", TwoFactorRequiredError),
)


def fetch_dashboard(cfg: Config) -> dict[str, Any]:
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=cfg.headless)
            try:
                context = browser.new_context(locale="de-DE")
                page = context.new_page()
                page.set_default_timeout(cfg.timeout_ms)
                return _login_and_capture(page, cfg)
            finally:
                browser.close()
    except PlaywrightError as exc:
        raise FetchError(f"browser error: {exc}") from exc


def _login_and_capture(page: Page, cfg: Config) -> dict[str, Any]:
    captured: list[Response] = []

    def remember_shift_response(response: Response) -> None:
        if SHIFT_ENDPOINT in response.url:
            captured.append(response)

    page.on("response", remember_shift_response)

    log.info("opening login page %s", cfg.base_url + LOGIN_PATH)
    page.goto(cfg.base_url + LOGIN_PATH)
    page.locator("#username").wait_for(state="visible")
    _raise_on_challenge(page)

    page.fill("#username", cfg.username)
    page.fill("#password", cfg.password)
    page.click("#submit")
    log.info("login submitted, waiting for roster response")

    response = _wait_for_response(page, captured, cfg.timeout_ms)
    return _decode(response)


def _wait_for_response(
    page: Page, captured: list[Response], timeout_ms: int
) -> Response:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if captured:
            return captured[0]
        _raise_on_challenge(page)
        page.wait_for_timeout(POLL_MS)
    raise LoginError(f"no roster response within {timeout_ms} ms (wrong credentials?)")


def _raise_on_challenge(page: Page) -> None:
    for selector, error in CHALLENGES:
        if page.locator(selector).is_visible():
            raise error(f"login blocked: {selector} is shown, log in manually once")


def _decode(response: Response) -> dict[str, Any]:
    if response.status != 200:
        raise FetchError(f"roster endpoint returned HTTP {response.status}")
    try:
        data = response.json()
    except (PlaywrightError, json.JSONDecodeError) as exc:
        raise FetchError("roster endpoint returned no JSON") from exc
    if not isinstance(data, dict):
        raise FetchError("roster JSON is not an object")
    return data
