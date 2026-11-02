import json
from pathlib import Path

import pytest

from pep_scraper.state import load_tracked_types, save_tracked_types

URL = "https://family.example"


def test_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    save_tracked_types(path, URL, {3: "2026-11-01T23:28:24Z", 1: "x"})
    assert load_tracked_types(path, URL) == {1: "x", 3: "2026-11-01T23:28:24Z"}
    assert path.stat().st_mode & 0o777 == 0o600


def test_other_instance_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    save_tracked_types(path, URL, {3: "x"})
    assert load_tracked_types(path, "https://other.example") == {}


def test_legacy_format_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"yuvomi_shift_type_ids": [10, 11]}), encoding="utf-8")
    assert load_tracked_types(path, URL) == {}


def test_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_tracked_types(tmp_path / "nope.json", URL) == {}


@pytest.mark.parametrize(
    "content",
    [
        "kaputt",
        "[]",
        '{"yuvomi_shift_type_ids": ["a"]}',
        '{"yuvomi_shift_type_ids": [true]}',
        '{"yuvomi_shift_type_ids": [0]}',
        '{"base_url": "https://family.example", "shift_types": {"x": "t"}}',
        '{"base_url": "https://family.example", "shift_types": {"-1": "t"}}',
    ],
)
def test_corrupt_file_is_empty(tmp_path: Path, content: str) -> None:
    path = tmp_path / "state.json"
    path.write_text(content, encoding="utf-8")
    assert load_tracked_types(path, URL) == {}
