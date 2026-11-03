"""Small file helpers."""

import os
import tempfile
from pathlib import Path


def write_private_atomic(path: Path, data: bytes) -> None:
    """Write via a private (0600) temp file in the same dir, then rename."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as tmp:
        try:
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        except BaseException:
            Path(tmp.name).unlink(missing_ok=True)
            raise
    try:
        Path(tmp.name).replace(path)
    except BaseException:
        Path(tmp.name).unlink(missing_ok=True)
        raise
