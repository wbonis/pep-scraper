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


YUV = {
    "YUVOMI_BASE_URL": "https://family.example/",
    "YUVOMI_API_KEY": "k",
    "YUVOMI_USER_ID": "4",
}


def test_yuvomi_disabled_by_default() -> None:
    assert load_config(BASE).yuvomi is None


def test_yuvomi_config() -> None:
    y = load_config({**BASE, **YUV}).yuvomi
    assert y is not None
    assert (y.base_url, y.api_key, y.user_id) == ("https://family.example", "k", 4)
    assert y.absences.value == "neutral"
    assert "k" not in repr(y).replace("yuvomi", "")


@pytest.mark.parametrize("missing", ["YUVOMI_API_KEY", "YUVOMI_USER_ID"])
def test_yuvomi_partial_config_rejected(missing: str) -> None:
    env = {k: v for k, v in {**BASE, **YUV}.items() if k != missing}
    with pytest.raises(ConfigError, match=missing):
        load_config(env)


def test_yuvomi_absence_mode() -> None:
    y = load_config({**BASE, **YUV, "YUVOMI_ABSENCES": "skip"}).yuvomi
    assert y is not None and y.absences.value == "skip"
    with pytest.raises(ConfigError, match="YUVOMI_ABSENCES"):
        load_config({**BASE, **YUV, "YUVOMI_ABSENCES": "maybe"})


def test_yuvomi_requires_https() -> None:
    with pytest.raises(ConfigError, match="YUVOMI_BASE_URL"):
        load_config({**BASE, **YUV, "YUVOMI_BASE_URL": "http://family.example"})


def test_url_error_hides_credentials() -> None:
    with pytest.raises(ConfigError) as info:
        load_config({**BASE, "PEP_BASE_URL": "http://user:secret@host.example"})
    assert "secret" not in str(info.value)
