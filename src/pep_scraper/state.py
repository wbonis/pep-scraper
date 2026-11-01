"""Local state: ids of Yuvomi shift types this tool created.

Yuvomi shift types have no marker field, so the tool remembers which types it
created itself. Only those are ever deleted once LOGA no longer uses them.
"""

import json
import logging
from pathlib import Path

from .files import write_private_atomic

log = logging.getLogger(__name__)

KEY = "yuvomi_shift_type_ids"


def load_tracked_types(path: Path) -> frozenset[int]:
    if not path.exists():
        return frozenset()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ids = data[KEY]
        if not all(isinstance(i, int) for i in ids):
            raise TypeError("ids must be integers")
        return frozenset(ids)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("Statusdatei %s unlesbar, starte leer: %s", path, exc)
        return frozenset()


def save_tracked_types(path: Path, ids: frozenset[int]) -> None:
    payload = json.dumps({KEY: sorted(ids)}, indent=2) + "\n"
    write_private_atomic(path, payload.encode("utf-8"))
