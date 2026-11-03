import os
from pathlib import Path

import pytest

from pep_scraper.browser_cache import (
    PROFILE_NAME,
    browser_args,
    prepare_profile,
    scrub_profile,
)


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def test_creates_private_dirs(tmp_path: Path) -> None:
    root = tmp_path / "a" / "c"
    profile = prepare_profile(root)
    assert profile == root / PROFILE_NAME
    assert _mode(root) == 0o700 and _mode(profile) == 0o700


def test_readable_own_dir_is_tightened(tmp_path: Path) -> None:
    root = tmp_path / "c"
    root.mkdir()
    root.chmod(0o755)
    assert prepare_profile(root) == root / PROFILE_NAME
    assert _mode(root) == 0o700


def test_bad_profile_subdir_is_rebuilt(tmp_path: Path) -> None:
    root = tmp_path / "c"
    root.mkdir(mode=0o700)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "planted").write_text("x")
    (root / PROFILE_NAME).symlink_to(elsewhere)
    profile = prepare_profile(root)
    assert profile is not None and not profile.is_symlink()
    assert _mode(profile) == 0o700
    assert (elsewhere / "planted").exists()  # symlink target never touched


def test_open_profile_subdir_is_rebuilt(tmp_path: Path) -> None:
    root = tmp_path / "c"
    profile = root / PROFILE_NAME
    (profile / "Default" / "Cache").mkdir(parents=True)
    (profile / "Default" / "Cache" / "poisoned").write_text("x")
    profile.chmod(0o777)
    root.chmod(0o700)
    assert prepare_profile(root) == profile
    assert _mode(profile) == 0o700
    assert not (profile / "Default").exists()


def test_symlink_root_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    (tmp_path / "c").symlink_to(real)
    assert prepare_profile(tmp_path / "c") is None


def test_file_instead_of_dir_is_refused(tmp_path: Path) -> None:
    (tmp_path / "c").write_text("x")
    assert prepare_profile(tmp_path / "c") is None


def test_uncreatable_is_refused(tmp_path: Path) -> None:
    (tmp_path / "file").write_text("x")
    assert prepare_profile(tmp_path / "file" / "c") is None


def test_parent_writable_by_others_is_refused(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o777)
    assert prepare_profile(shared / "c") is None


def test_sticky_parent_is_fine(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o1777)
    assert prepare_profile(shared / "c") is not None


def test_scrub_keeps_only_http_and_code_cache(tmp_path: Path) -> None:
    profile = tmp_path / PROFILE_NAME
    default = profile / "Default"
    for name in ("Cache", "Code Cache", "Local Storage", "Service Worker"):
        (default / name).mkdir(parents=True)
        (default / name / "f").write_text("x")
    for name in ("Cookies", "Login Data", "Web Data"):
        (default / name).write_text("x")
    (profile / "Local State").write_text("x")
    (profile / "Crashpad").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (default / "Link").symlink_to(outside)
    scrub_profile(profile)
    assert sorted(p.name for p in profile.iterdir()) == ["Default"]
    assert sorted(p.name for p in default.iterdir()) == ["Cache", "Code Cache"]
    assert (default / "Cache" / "f").exists() and outside.exists()


def test_scrub_removes_symlinked_cache(tmp_path: Path) -> None:
    profile = tmp_path / PROFILE_NAME
    (profile / "Default").mkdir(parents=True)
    target = tmp_path / "t"
    target.mkdir()
    (profile / "Default" / "Cache").symlink_to(target)
    scrub_profile(profile)
    assert list((profile / "Default").iterdir()) == [] and target.exists()


def test_scrub_missing_profile_is_fine(tmp_path: Path) -> None:
    scrub_profile(tmp_path / "nope")


def test_disk_cache_holds_large_app_file() -> None:
    (arg,) = browser_args()
    size = int(arg.removeprefix("--disk-cache-size="))
    assert size // 8 >= 100 * 1024 * 1024  # Chromium caches files up to 1/8 of it


def test_not_owned_dir_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "c"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(os, "getuid", lambda: 12345)
    assert prepare_profile(root) is None
