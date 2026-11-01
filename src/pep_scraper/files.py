"""Small file helpers."""

import tempfile
from pathlib import Path


def write_private_atomic(path: Path, data: bytes) -> None:
    """Write via a private (0600) temp file in the same dir, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as tmp:
        tmp.write(data)
    Path(tmp.name).replace(path)
