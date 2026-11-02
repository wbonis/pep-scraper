"""Switches from the ``[einstellungen]`` section of ``schichten.toml``."""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import time, timedelta
from pathlib import Path
from typing import Literal, cast

from .naming import SETTINGS_SECTION, NamesError, norm, read_toml

CreditMode = Literal["termin", "info"]
BreakMode = Literal["kuerzen", "info"]
CREDIT_MODES: tuple[CreditMode, ...] = ("termin", "info")
BREAK_MODES: tuple[BreakMode, ...] = ("kuerzen", "info")
DAYS_PER_WEEK = 5
MAX_HOURS = 24
MAX_WEEK_HOURS = MAX_HOURS * 7
MAX_BREAK_MINUTES = MAX_HOURS * 60

DEFAULT_HOLIDAYS = frozenset({"feiertag", "feiertage", "betrieblich freier tag"})

KEYS = frozenset(
    {
        "feiertagsregel",
        "feiertage",
        "neue_codes_eintragen",
        "gutschrift",
        "gutschrift_modus",
        "schicht_start",
        "stunden_pro_tag",
        "stunden_pro_woche",
        "pause_minuten",
        "pause_ab_stunden",
        "pause_modus",
    }
)


@dataclass(frozen=True, slots=True)
class Credit:
    """Work time credited for all-day entries such as Urlaub (Arbeitszeitäquivalent)."""

    titles: frozenset[str] = frozenset()  # normalised, empty = off
    mode: CreditMode = "termin"
    start: time = time(8, 0)
    hours: timedelta = timedelta(hours=8)


@dataclass(frozen=True, slots=True)
class BreakRule:
    """Break deducted from the end of a shift (Pausenabzug)."""

    minutes: int = 0  # 0 = off
    min_length: timedelta = timedelta(0)  # only shifts longer than this
    mode: BreakMode = "kuerzen"


@dataclass(frozen=True, slots=True)
class Settings:
    holiday_rule: bool = True
    holiday_titles: frozenset[str] = DEFAULT_HOLIDAYS
    add_new_codes: bool = True
    credit: Credit = field(default_factory=Credit)
    pause: BreakRule = field(default_factory=BreakRule)


def load_settings(path: Path) -> Settings:
    raw = read_toml(path).get(SETTINGS_SECTION, {})
    if not isinstance(raw, dict):
        raise _error(path, "muss ein Abschnitt sein")
    unknown = set(raw) - KEYS
    if unknown:
        raise _error(path, f"unbekannte Schlüssel: {sorted(unknown)}")
    return Settings(
        holiday_rule=_bool(path, raw, "feiertagsregel", True),
        holiday_titles=_titles(path, raw, "feiertage", DEFAULT_HOLIDAYS),
        add_new_codes=_bool(path, raw, "neue_codes_eintragen", True),
        credit=Credit(
            titles=_titles(path, raw, "gutschrift", frozenset()),
            mode=cast(CreditMode, _choice(path, raw, "gutschrift_modus", CREDIT_MODES)),
            start=_clock(path, raw, "schicht_start", time(8, 0)),
            hours=_daily_hours(path, raw),
        ),
        pause=BreakRule(
            minutes=_minutes(path, raw),
            min_length=timedelta(
                hours=_number(path, raw, "pause_ab_stunden", 0, 0, MAX_HOURS)
            ),
            mode=cast(BreakMode, _choice(path, raw, "pause_modus", BREAK_MODES)),
        ),
    )


def _error(path: Path, text: str) -> NamesError:
    return NamesError(f"{path}: [{SETTINGS_SECTION}] {text}")


def _bool(path: Path, raw: Mapping[str, object], key: str, default: bool) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise _error(path, f"{key} muss true oder false sein")
    return value


def _titles(
    path: Path, raw: Mapping[str, object], key: str, default: frozenset[str]
) -> frozenset[str]:
    if key not in raw:
        return default
    value = raw[key]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise _error(path, f'{key} muss eine Liste sein, z. B. ["Urlaub"]')
    return frozenset(norm(v) for v in value)


def _choice(
    path: Path, raw: Mapping[str, object], key: str, allowed: tuple[str, ...]
) -> str:
    value = raw.get(key, allowed[0])
    if value not in allowed:
        raise _error(path, f"{key} muss einer von {', '.join(allowed)} sein")
    return str(value)


def _clock(path: Path, raw: Mapping[str, object], key: str, default: time) -> time:
    value = raw.get(key)
    if value is None:
        return default
    try:
        if not isinstance(value, str):
            raise TypeError(value)
        return time.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise _error(path, f'{key} muss eine Uhrzeit sein, z. B. "08:00"') from exc


def _number(
    path: Path,
    raw: Mapping[str, object],
    key: str,
    default: float,
    low: float,
    high: float,
) -> float:
    value = raw.get(key, default)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise _error(path, f"{key} muss eine Zahl sein")
    try:
        number = float(value)
    except OverflowError as exc:  # TOML ints have no size limit
        raise _error(path, f"{key} ist zu groß") from exc
    if not math.isfinite(number) or not low <= number <= high:
        raise _error(path, f"{key} muss zwischen {low:g} und {high:g} liegen")
    return number


def _daily_hours(path: Path, raw: Mapping[str, object]) -> timedelta:
    if "stunden_pro_tag" in raw and "stunden_pro_woche" in raw:
        raise _error(path, "nur stunden_pro_tag oder stunden_pro_woche angeben")
    if "stunden_pro_woche" in raw:
        week = _number(path, raw, "stunden_pro_woche", 40, 0, MAX_WEEK_HOURS)
        hours = week / DAYS_PER_WEEK
    else:
        hours = _number(path, raw, "stunden_pro_tag", 8, 0, MAX_HOURS)
    if not 0 < hours <= MAX_HOURS:
        raise _error(path, f"Stunden pro Tag müssen über 0 und bis {MAX_HOURS} sein")
    return timedelta(hours=hours)


def _minutes(path: Path, raw: Mapping[str, object]) -> int:
    value = raw.get("pause_minuten", 0)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= MAX_BREAK_MINUTES
    ):
        raise _error(
            path,
            f"pause_minuten muss eine ganze Zahl von 0 bis {MAX_BREAK_MINUTES} sein",
        )
    return value
