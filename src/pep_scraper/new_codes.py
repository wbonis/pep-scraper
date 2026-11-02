"""Append LOGA shift codes missing from ``schichten.toml`` to that file.

Only shift codes are added, never absence titles: a named absence title is
shown in Yuvomi, so adding one would have to be a deliberate choice. For the
same reason a code equal to an absence title or looking like a health reason
is never added.
"""

import json
import os
import re
import tomllib
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path

from .files import write_private_atomic
from .models import RosterEvent
from .naming import (
    MAX_NAME,
    SETTINGS_SECTION,
    NameEntry,
    heuristic,
    is_health_reason,
)

BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")
HEADER = "# Lesbare Namen für LOGA-Dienstcodes (siehe schichten.example.toml).\n"
DEFAULT_MODE = 0o600

NewCode = tuple[str, NameEntry]


def unknown_codes(
    events: Iterable[RosterEvent], names: Mapping[str, NameEntry]
) -> tuple[NewCode, ...]:
    """Shift codes of these events without an entry in ``names``, first seen first."""
    events = tuple(events)
    absence_titles = {e.code for e in events if e.kind == "absence"}
    found: dict[str, NameEntry] = {}
    for event in events:
        code = event.code
        if event.kind == "absence" or code in names or code in found:
            continue
        if _addable(code, event.summary, absence_titles):
            found[code] = heuristic(event) or NameEntry(_clean(event.summary))
    return tuple(found.items())


def _addable(code: str, summary: str, absence_titles: set[str]) -> bool:
    if not code or code == SETTINGS_SECTION or not code.isprintable():
        return False  # isprintable() also rejects DEL and lone surrogates
    if code in absence_titles:
        return False
    return not (is_health_reason(code) or is_health_reason(summary))


def append_codes(path: Path, codes: Iterable[NewCode], today: date) -> None:
    """Add entries at the end; existing content and comments stay as they are.

    Re-reads the file first and skips codes added meanwhile. Raises ValueError
    instead of writing a file that would no longer parse.
    """
    target = path.resolve()  # keep a symlinked schichten.toml a symlink
    old = target.read_text(encoding="utf-8") if target.exists() else HEADER
    present = tomllib.loads(old)
    blocks = [_block(c, e, today) for c, e in codes if c not in present]
    if not blocks:
        return
    if not old.endswith("\n"):
        old += "\n"
    new = old + "".join(blocks)
    tomllib.loads(new)  # never write a file the next run cannot read
    mode = target.stat().st_mode & 0o777 if target.exists() else DEFAULT_MODE
    write_private_atomic(target, new.encode("utf-8"))
    os.chmod(target, mode)


def _block(code: str, entry: NameEntry, today: date) -> str:
    key = code if BARE_KEY_RE.match(code) else _quote(code)
    lines = [
        "",
        f"# automatisch eingetragen am {today.isoformat()}, Namen bei Bedarf anpassen",
        f"[{key}]",
        f"name = {_quote(entry.name)}",
    ]
    if entry.icon:
        lines.append(f"icon = {_quote(entry.icon)}")
    return "\n".join(lines) + "\n"


def _quote(text: str) -> str:
    """TOML basic string; JSON escaping is a valid subset for printable text."""
    return json.dumps(text, ensure_ascii=False)


def _clean(text: str) -> str:
    printable = "".join(ch if ch.isprintable() else " " for ch in text)
    return " ".join(printable.split())[:MAX_NAME].strip() or "Dienst"
