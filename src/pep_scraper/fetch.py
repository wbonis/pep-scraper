"""Log in to LOGA3 with a headless browser and capture the PEP shift JSON.

The dashboard's own JS requests ``pep/loadShiftsDashboard`` (incl. xsrf token)
after login; we only listen for that response instead of re-implementing
the GWT session/xsrf handling.
"""

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from playwright.sync_api import (
    BrowserContext,
)
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, Playwright, Response, sync_playwright

from .browser_cache import browser_args, prepare_profile, scrub_profile
from .config import Config

log = logging.getLogger(__name__)

SHIFT_ENDPOINT = "/api/dashboard/pep/loadShiftsDashboard"
LOGIN_PATH = "/loga3/"
PRIVATE_PATH = "/private/"
POLL_MS = 250

# LOGA login page: hidden ".message.alert" boxes, shown on errors.
# These ones mean "try again later", not "wrong credentials".
MAINTENANCE_BOXES = frozenset(
    {"loginLocked", "dbNotActive", "externTemplateTenantLoginLocked"}
)

VISIBLE_MESSAGES_JS = """() =>
  [...document.querySelectorAll('.message.alert, #message')]
  .filter(e => e.offsetParent !== null && e.innerText.trim())
  .map(e => [e.id, e.innerText.trim()])"""


class FetchError(RuntimeError):
    """Roster could not be retrieved."""


class MaintenanceError(FetchError):
    """LOGA is locked for maintenance; retry later."""


class LoginError(FetchError):
    """Login did not succeed."""


class CaptchaRequiredError(LoginError):
    """Server shows a captcha; manual login needed."""


class TwoFactorRequiredError(LoginError):
    """Server asks for a 2FA token."""


class PasswordExpiredError(LoginError):
    """LOGA asks for a new password after login."""


CHALLENGES: tuple[tuple[str, type[LoginError], str], ...] = (
    ("#captchaInput", CaptchaRequiredError, "LOGA verlangt ein Captcha"),
    ("#twofatoken", TwoFactorRequiredError, "LOGA verlangt einen 2FA-Code"),
)


def fetch_dashboard(cfg: Config) -> dict[str, Any]:
    try:
        with sync_playwright() as pw:
            context, close = _open_context(pw, cfg)
            try:
                page = context.new_page()
                page.set_default_timeout(cfg.timeout_ms)
                return _login_and_capture(page, cfg)
            finally:
                close()
    except PlaywrightError as exc:
        raise FetchError(f"Browser-Fehler: {exc}") from exc


def _open_context(
    pw: Playwright, cfg: Config
) -> tuple[BrowserContext, Callable[[], None]]:
    """Persistent profile (keeps LOGA's app code cached) or a throwaway one.

    The profile is scrubbed to its HTTP/code cache before (prepare_profile)
    and after each run, so no cookie, storage or service worker survives.
    """
    profile = prepare_profile(cfg.cache_dir) if cfg.cache_dir is not None else None
    if profile is None:
        browser = pw.chromium.launch(headless=cfg.headless)
        return browser.new_context(locale="de-DE"), browser.close
    context = pw.chromium.launch_persistent_context(
        profile,
        headless=cfg.headless,
        locale="de-DE",
        args=browser_args(),
        service_workers="block",
    )

    def close() -> None:
        try:
            context.close()
        finally:
            _scrub_after_run(profile)

    return context, close


def _scrub_after_run(profile: Path) -> None:
    try:
        scrub_profile(profile)
    except OSError as exc:  # next run scrubs again before starting
        log.warning("Browser-Profil %s nicht bereinigt: %s", profile, exc)


def _login_and_capture(page: Page, cfg: Config) -> dict[str, Any]:
    captured: list[Response] = []

    def remember_shift_response(response: Response) -> None:
        if SHIFT_ENDPOINT in response.url:
            captured.append(response)

    page.on("response", remember_shift_response)

    log.info("öffne Anmeldeseite %s", cfg.base_url + LOGIN_PATH)
    page.goto(cfg.base_url + LOGIN_PATH)
    page.locator("#username").wait_for(state="visible")
    _raise_on_challenge(page)

    page.fill("#username", cfg.username)
    page.fill("#password", cfg.password)
    page.click("#submit")
    log.info("Anmeldung abgeschickt, warte auf Dienstplan")

    response = _wait_for_response(page, captured, cfg.timeout_ms)
    return _decode(response)


def _wait_for_response(
    page: Page, captured: list[Response], timeout_ms: int
) -> Response:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if captured:
            return captured[0]
        _check_page(page)
        page.wait_for_timeout(POLL_MS)
    if PRIVATE_PATH in page.url:
        raise FetchError(f"angemeldet, aber kein Dienstplan nach {timeout_ms} ms")
    raise LoginError(f"keine Antwort nach {timeout_ms} ms (Zugangsdaten falsch?)")


def _check_page(page: Page) -> None:
    """Raise as soon as the page shows why the roster will not come."""
    try:
        _raise_on_challenge(page)
        _raise_on_login_message(page)
        _raise_on_password_change(page)
    except PlaywrightError:
        return  # page is navigating; check again on the next poll


def _raise_on_challenge(page: Page) -> None:
    for selector, error, text in CHALLENGES:
        if page.locator(selector).is_visible():
            raise error(f"{text} - einmal im Browser von Hand anmelden")


def _raise_on_login_message(page: Page) -> None:
    if PRIVATE_PATH in page.url:
        return
    messages: list[list[str]] = page.evaluate(VISIBLE_MESSAGES_JS)
    for box_id, raw_text in messages:
        text = " ".join(raw_text.split())[:200]  # one line, bounded, for the log
        if box_id in MAINTENANCE_BOXES:
            raise MaintenanceError(f"LOGA gesperrt: {text}")
        raise LoginError(f"Anmeldung abgelehnt: {text}")


def _raise_on_password_change(page: Page) -> None:
    """A password field inside the logged-in app means: set a new password."""
    if PRIVATE_PATH in page.url and page.locator("input[type=password]").is_visible():
        raise PasswordExpiredError(
            "LOGA verlangt ein neues Kennwort - im Browser ändern, "
            "dann PEP_PASSWORD anpassen"
        )


def _decode(response: Response) -> dict[str, Any]:
    if response.status != 200:
        raise FetchError(f"Dienstplan-Abruf lieferte HTTP {response.status}")
    try:
        data = response.json()
    except (PlaywrightError, json.JSONDecodeError) as exc:
        raise FetchError("Dienstplan-Abruf lieferte kein JSON") from exc
    if not isinstance(data, dict):
        raise FetchError("Dienstplan-JSON ist kein Objekt")
    return data
