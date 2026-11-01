from pathlib import Path

import pytest

from pep_scraper.config import Config, ConfigError, load_config

BASE = {"PEP_USERNAME": "user", "PEP_PASSWORD": "pw"}


def test_defaults() -> None:
    cfg = load_config(BASE)
    assert cfg == Config(
        username="user",
        password="pw",
        base_url="https://harzklinikum.pi-asp.de",
        output=Path("dienstplan.ics"),
        headless=True,
        timeout_ms=60_000,
        tz_name="Europe/Berlin",
    )


def test_overrides() -> None:
    cfg = load_config(
        {
            **BASE,
            "PEP_BASE_URL": "https://example.test/",
            "PEP_OUTPUT": "/tmp/x.ics",
            "PEP_HEADLESS": "false",
            "PEP_TIMEOUT_MS": "5000",
            "PEP_TZ": "UTC",
        }
    )
    assert cfg.base_url == "https://example.test"
    assert cfg.output == Path("/tmp/x.ics")
    assert cfg.headless is False
    assert cfg.timeout_ms == 5000
    assert cfg.tz_name == "UTC"


@pytest.mark.parametrize("missing", ["PEP_USERNAME", "PEP_PASSWORD"])
def test_missing_credentials(missing: str) -> None:
    env = {k: v for k, v in BASE.items() if k != missing}
    with pytest.raises(ConfigError, match=missing):
        load_config(env)


def test_bad_timeout() -> None:
    with pytest.raises(ConfigError, match="PEP_TIMEOUT_MS"):
        load_config({**BASE, "PEP_TIMEOUT_MS": "abc"})


def test_password_not_in_repr() -> None:
    assert "pw" not in repr(load_config(BASE))


@pytest.mark.parametrize(
    "url", ["http://harzklinikum.pi-asp.de", "ftp://x", "harzklinikum.pi-asp.de"]
)
def test_non_https_base_url_rejected(url: str) -> None:
    with pytest.raises(ConfigError, match="PEP_BASE_URL"):
        load_config({**BASE, "PEP_BASE_URL": url})


@pytest.mark.parametrize("url", ["http://127.0.0.1:8080", "http://localhost"])
def test_http_allowed_for_localhost(url: str) -> None:
    assert load_config({**BASE, "PEP_BASE_URL": url}).base_url == url
