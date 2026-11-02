"""Local state: Yuvomi shift types this tool created.

Yuvomi shift types have no marker field, so the tool remembers which types it
created itself: id plus ``created_at`` as fingerprint, bound to the Yuvomi URL.
Only those are ever deleted once LOGA no longer uses them.
"""

import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .files import write_private_atomic

log = logging.getLogger(__name__)


def load_tracked_types(path: Path, base_url: str) -> dict[int, str]:
    """Return {type id: created_at}; "" = fingerprint not known yet."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return _parse(data, base_url, path)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        log.warning("Statusdatei %s unlesbar, starte leer: %s", path, exc)
        return {}


def _parse(data: Any, base_url: str, path: Path) -> dict[int, str]:
    if data["base_url"] != base_url:
        log.warning(
            "Statusdatei %s gehört zu %s, nicht zu %s - ignoriert",
            path,
            data["base_url"],
            base_url,
        )
        return {}
    return {_valid_id(int(k)): str(v) for k, v in data["shift_types"].items()}


def _valid_id(value: Any) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"ungültige Typ-Id {value!r}")
    return value


def save_tracked_types(path: Path, base_url: str, tracked: Mapping[int, str]) -> None:
    payload = {
        "base_url": base_url,
        "shift_types": {str(k): tracked[k] for k in sorted(tracked)},
    }
    write_private_atomic(path, (json.dumps(payload, indent=2) + "\n").encode("utf-8"))
