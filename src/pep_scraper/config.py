"""Configuration from environment (.env)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_BASE_URL = "https://harzklinikum.pi-asp.de"
DEFAULT_OUTPUT = "dienstplan.ics"
DEFAULT_TIMEOUT_MS = 60_000
DEFAULT_TZ = "Europe/Berlin"
FALSE_VALUES = frozenset({"0", "false", "no"})
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class ConfigError(ValueError):
    """Missing or invalid configuration."""


@dataclass(frozen=True, slots=True)
class Config:
    username: str
    password: str = field(repr=False)
    base_url: str
    output: Path
    headless: bool
    timeout_ms: int
    tz_name: str


def load_config(env: Mapping[str, str]) -> Config:
    return Config(
        username=_required(env, "PEP_USERNAME"),
        password=_required(env, "PEP_PASSWORD"),
        base_url=_base_url(env.get("PEP_BASE_URL", DEFAULT_BASE_URL)),
        output=Path(env.get("PEP_OUTPUT", DEFAULT_OUTPUT)),
        headless=_bool(env, "PEP_HEADLESS", default=True),
        timeout_ms=_int(env, "PEP_TIMEOUT_MS", DEFAULT_TIMEOUT_MS),
        tz_name=env.get("PEP_TZ", DEFAULT_TZ),
    )


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ConfigError(f"{key} is not set (see .env.example)")
    return value


def _base_url(raw: str) -> str:
    url = urlsplit(raw.strip())
    plain_http_ok = url.scheme == "http" and url.hostname in LOCAL_HOSTS
    if not url.hostname or (url.scheme != "https" and not plain_http_ok):
        raise ConfigError(f"PEP_BASE_URL must be an https:// URL, got {raw!r}")
    return raw.strip().rstrip("/")


def _bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    return raw.strip().lower() not in FALSE_VALUES


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from exc
