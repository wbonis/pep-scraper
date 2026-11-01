from pathlib import Path

import pytest

from pep_scraper.state import load_tracked_types, save_tracked_types


def test_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    save_tracked_types(path, frozenset({3, 1}))
    assert load_tracked_types(path) == frozenset({1, 3})
    assert path.stat().st_mode & 0o777 == 0o600


def test_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_tracked_types(tmp_path / "nope.json") == frozenset()


@pytest.mark.parametrize(
    "content", ["kaputt", "[]", '{"yuvomi_shift_type_ids": ["a"]}']
)
def test_corrupt_file_is_empty(tmp_path: Path, content: str) -> None:
    path = tmp_path / "state.json"
    path.write_text(content, encoding="utf-8")
    assert load_tracked_types(path) == frozenset()
