"""Readable names for LOGA shift codes and absence titles.

Source order: entry in ``schichten.toml`` (key = LOGA code or absence title),
then a rule of thumb for shift codes (F.. Frühdienst, S.. Spätdienst,
N.. Nachtdienst), else the LOGA text stays as it is.
"""

import re
import tomllib
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from .models import RosterEvent

ICON_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")  # Yuvomi/lucide icon names
MAX_NAME = 100


class NamesError(ValueError):
    """schichten.toml is invalid."""


@dataclass(frozen=True, slots=True)
class NameEntry:
    name: str
    icon: str | None = None


HEURISTICS: tuple[tuple[re.Pattern[str], NameEntry], ...] = (
    (re.compile(r"^F\d"), NameEntry("Frühdienst", "sunrise")),
    (re.compile(r"^S\d"), NameEntry("Spätdienst", "sunset")),
    (re.compile(r"^N\d"), NameEntry("Nachtdienst", "moon")),
)

# Health data (Art. 9 DSGVO). Matched on NFKC-normalised, casefolded text.
HEALTH_RE = re.compile(
    r"krank|krkh|erkr\.|arbeitsunf|unfall|\bau\b|\befz\b|\bkur(?!s)|reha|mutterschutz"
    r"|mutterschaft|schwanger|entbindung|stillzeit|besch(ä|ae)ftigungsverbot"
    r"|wiedereingliederung|hamburger modell|schwerbehind|\bsb-|\bgdb\b|arzt|attest"
    r"|quarant(ä|ae)ne|therapie|heilverfahren|impf|covid|corona|\bbem\b"
)

# Absence titles that are no health data and may be shown with their title.
# Every other title is hidden as "Abwesend" unless named in schichten.toml.
HARMLESS_ABSENCES = frozenset(
    {
        "urlaub",
        "jahresurlaub",
        "resturlaub",
        "fortbildung",
        "weiterbildung",
        "fachweiterbildung",
        "schule",
        "berufsschule",
        "feiertag",
        "betrieblich freier tag",
        "dienstreise",
        "freizeitausgleich",
        "überstundenabbau",
        "elternzeit",
    }
)


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().strip()


def is_health_reason(title: str) -> bool:
    """Absence reasons that are health data and must not be shown to others."""
    return HEALTH_RE.search(_norm(title)) is not None


def is_shown_absence(title: str, named: frozenset[str]) -> bool:
    """Fail closed: show only known-harmless or deliberately named titles,
    never health reasons."""
    if is_health_reason(title):
        return False
    return _norm(title) in HARMLESS_ABSENCES or title in named


def load_names(path: Path) -> dict[str, NameEntry]:
    if not path.exists():
        return {}
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # incl. TOML and UTF-8 decode errors
        raise NamesError(f"{path}: {exc}") from exc
    return {str(key): _entry(path, str(key), value) for key, value in raw.items()}


def _entry(path: Path, key: str, value: object) -> NameEntry:
    if not isinstance(value, dict) or not isinstance(value.get("name"), str):
        raise NamesError(f'{path}: [{key}] braucht name = "..."')
    unknown = set(value) - {"name", "icon"}
    if unknown:
        raise NamesError(f"{path}: [{key}] unbekannte Schlüssel: {sorted(unknown)}")
    name = value["name"].strip()
    if not 1 <= len(name) <= MAX_NAME or not name.isprintable():
        raise NamesError(
            f"{path}: [{key}] name muss 1-{MAX_NAME} lesbare Zeichen haben"
        )
    icon = value.get("icon")
    if icon is not None and (not isinstance(icon, str) or not ICON_RE.match(icon)):
        raise NamesError(f"{path}: [{key}] icon muss z. B. 'sunset' sein")
    return NameEntry(name, icon)


def apply_names(
    events: Iterable[RosterEvent], names: Mapping[str, NameEntry]
) -> tuple[RosterEvent, ...]:
    return tuple(_named(event, names) for event in events)


def _named(event: RosterEvent, names: Mapping[str, NameEntry]) -> RosterEvent:
    entry = names.get(event.code) or _heuristic(event)
    if entry is None:
        return event
    return replace(event, summary=entry.name, icon=entry.icon)


def _heuristic(event: RosterEvent) -> NameEntry | None:
    if event.kind != "shift":
        return None
    return next((entry for rx, entry in HEURISTICS if rx.match(event.code)), None)
