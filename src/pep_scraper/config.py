"""Konfiguration aus der Umgebung (.env)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .yuvomi_plan import AbsenceMode

DEFAULT_BASE_URL = "https://harzklinikum.pi-asp.de"
DEFAULT_OUTPUT = "dienstplan.ics"
DEFAULT_TIMEOUT_MS = 60_000
DEFAULT_TZ = "Europe/Berlin"
DEFAULT_STATE_FILE = ".pep-scraper-state.json"
DEFAULT_NAMES_FILE = "schichten.toml"
FALSE_VALUES = frozenset({"0", "false", "no"})
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class ConfigError(ValueError):
    """Missing or invalid configuration."""


@dataclass(frozen=True, slots=True)
class YuvomiConfig:
    base_url: str
    api_key: str = field(repr=False)
    user_id: int
    absences: AbsenceMode
    state_file: Path = Path(DEFAULT_STATE_FILE)


@dataclass(frozen=True, slots=True)
class Config:
    username: str
    password: str = field(repr=False)
    base_url: str
    output: Path
    headless: bool
    timeout_ms: int
    tz_name: str
    names_file: Path = Path(DEFAULT_NAMES_FILE)
    yuvomi: YuvomiConfig | None = None


def load_config(env: Mapping[str, str]) -> Config:
    return Config(
        username=_required(env, "PEP_USERNAME"),
        password=_required(env, "PEP_PASSWORD"),
        base_url=_base_url(env.get("PEP_BASE_URL", DEFAULT_BASE_URL), "PEP_BASE_URL"),
        output=Path(env.get("PEP_OUTPUT", DEFAULT_OUTPUT)),
        headless=_bool(env, "PEP_HEADLESS", default=True),
        timeout_ms=_int(env, "PEP_TIMEOUT_MS", DEFAULT_TIMEOUT_MS),
        tz_name=env.get("PEP_TZ", DEFAULT_TZ),
        names_file=Path(env.get("PEP_NAMES_FILE", DEFAULT_NAMES_FILE)),
        yuvomi=_yuvomi(env),
    )


def _yuvomi(env: Mapping[str, str]) -> YuvomiConfig | None:
    """Optional: nur aktiv, wenn YUVOMI_BASE_URL oder YUVOMI_API_KEY gesetzt ist."""
    if not (
        env.get("YUVOMI_BASE_URL", "").strip() or env.get("YUVOMI_API_KEY", "").strip()
    ):
        return None
    raw_mode = env.get("YUVOMI_ABSENCES", AbsenceMode.NEUTRAL.value).strip().lower()
    try:
        mode = AbsenceMode(raw_mode)
    except ValueError as exc:
        allowed = ", ".join(m.value for m in AbsenceMode)
        raise ConfigError(
            f"YUVOMI_ABSENCES muss einer von {allowed} sein, ist aber {raw_mode!r}"
        ) from exc
    return YuvomiConfig(
        base_url=_base_url(_required(env, "YUVOMI_BASE_URL"), "YUVOMI_BASE_URL"),
        api_key=_required(env, "YUVOMI_API_KEY"),
        user_id=_int(env, "YUVOMI_USER_ID", None),
        absences=mode,
        state_file=Path(env.get("YUVOMI_STATE_FILE", DEFAULT_STATE_FILE)),
    )


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ConfigError(f"{key} ist nicht gesetzt (siehe .env.example)")
    return value


def _base_url(raw: str, key: str) -> str:
    url = urlsplit(raw.strip())
    if url.username or url.password:
        raise ConfigError(f"{key} darf keine Zugangsdaten enthalten")
    plain_http_ok = url.scheme == "http" and url.hostname in LOCAL_HOSTS
    if not url.hostname or (url.scheme != "https" and not plain_http_ok):
        shown = f"{url.scheme}://{url.hostname}" if url.hostname else "ungültige URL"
        raise ConfigError(f"{key} muss eine https://-URL sein, ist aber {shown}")
    return raw.strip().rstrip("/")


def _bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    return raw.strip().lower() not in FALSE_VALUES


def _int(env: Mapping[str, str], key: str, default: int | None) -> int:
    raw = env.get(key)
    if raw is None or not raw.strip():
        if default is None:
            raise ConfigError(f"{key} ist nicht gesetzt (siehe .env.example)")
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} muss eine ganze Zahl sein, ist aber {raw!r}") from exc
