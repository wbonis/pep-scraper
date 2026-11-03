import sys
from pathlib import Path

import pytest

from pep_scraper.config import Config, ConfigError, load_config

DEFAULT_CACHE = (
    Path.home() / "Library" / "Caches" / "pep-scraper"
    if sys.platform == "darwin"
    else Path.home() / ".cache" / "pep-scraper"
)

BASE = {
    "PEP_USERNAME": "user",
    "PEP_PASSWORD": "pw",
    "PEP_BASE_URL": "https://example.pi-asp.de",
}


def test_defaults() -> None:
    cfg = load_config(BASE)
    assert cfg == Config(
        username="user",
        password="pw",
        base_url="https://example.pi-asp.de",
        output=Path("dienstplan.ics"),
        headless=True,
        timeout_ms=180_000,
        tz_name="Europe/Berlin",
        names_file=Path("schichten.toml"),
        cache_dir=DEFAULT_CACHE,
    )


def test_cache_dir_from_xdg() -> None:
    cfg = load_config({**BASE, "XDG_CACHE_HOME": "/var/c"})
    assert cfg.cache_dir == Path("/var/c/pep-scraper")


def test_relative_xdg_is_ignored() -> None:
    cfg = load_config({**BASE, "XDG_CACHE_HOME": "rel/c"})
    assert cfg.cache_dir == DEFAULT_CACHE


def test_cache_dir_override_expands_home() -> None:
    cfg = load_config({**BASE, "PEP_CACHE_DIR": "~/x"})
    assert cfg.cache_dir == Path.home() / "x"


@pytest.mark.parametrize("value", ["off", "0", "false", "no", " OFF "])
def test_cache_dir_off(value: str) -> None:
    assert load_config({**BASE, "PEP_CACHE_DIR": value}).cache_dir is None


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


@pytest.mark.parametrize("missing", ["PEP_USERNAME", "PEP_PASSWORD", "PEP_BASE_URL"])
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
    "url", ["http://example.pi-asp.de", "ftp://x", "example.pi-asp.de"]
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


def test_yuvomi_state_file() -> None:
    y = load_config({**BASE, **YUV}).yuvomi
    assert y is not None and y.state_file == Path(".pep-scraper-state.json")
    y = load_config({**BASE, **YUV, "YUVOMI_STATE_FILE": "/var/lib/pep/s.json"}).yuvomi
    assert y is not None and y.state_file == Path("/var/lib/pep/s.json")


def test_names_file_override() -> None:
    assert load_config(
        {**BASE, "PEP_NAMES_FILE": "/etc/pep/n.toml"}
    ).names_file == Path("/etc/pep/n.toml")


def test_absence_mode_hidden() -> None:
    y = load_config({**BASE, **YUV, "YUVOMI_ABSENCES": "hidden"}).yuvomi
    assert y is not None and y.absences.value == "hidden"


def test_url_with_credentials_rejected() -> None:
    with pytest.raises(ConfigError, match="Zugangsdaten"):
        load_config({**BASE, "PEP_BASE_URL": "https://user:pw@host.example"})
