"""Persistent Chromium profile so LOGA's app code (~20 MB) is downloaded once.

LOGA serves its versioned app files with ``Cache-Control: max-age`` (31 days),
so Chromium's disk cache keeps them between runs. Everything else Chromium
stores in a profile (cookies, local storage, service workers, form data, ...)
is deleted before and after every run: only the HTTP cache and V8's code
cache stay. The cache feeds code into a logged-in session, so it is only used
in a private directory (0700) owned by the current user, inside parents that
nobody else can swap.
"""

import logging
import os
import shutil
import stat
from pathlib import Path

log = logging.getLogger(__name__)

PROFILE_NAME = "chromium"
KEEP = frozenset({"Cache", "Code Cache"})  # inside <profile>/Default
DISK_CACHE_BYTES = 1024**3  # Chromium caches one file up to 1/8 of this


class UnsafeCacheError(OSError):
    """Cache directory may be changed by someone else."""


def browser_args() -> list[str]:
    return [f"--disk-cache-size={DISK_CACHE_BYTES}"]


def prepare_profile(root: Path) -> Path | None:
    """Private, scrubbed profile dir inside ``root``; None (warning) if unsafe."""
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        _check_parents(root)
        _make_private(root)
        profile = root / PROFILE_NAME
        _reset_if_foreign(profile)
        profile.mkdir(mode=0o700, exist_ok=True)
        scrub_profile(profile)
    except OSError as exc:
        log.warning("Browser-Cache %s aus: %s", root, exc)
        return None
    return profile


def scrub_profile(profile: Path) -> None:
    """Delete everything except <profile>/Default/{Cache,Code Cache}."""
    if not profile.is_dir() or profile.is_symlink():
        return
    for child in profile.iterdir():
        if child.name != "Default" or child.is_symlink():
            _remove(child)
    default = profile / "Default"
    if default.is_dir() and not default.is_symlink():
        for child in default.iterdir():
            if child.name not in KEEP or child.is_symlink():
                _remove(child)


def _check_parents(root: Path) -> None:
    """Nobody else may rename or replace a directory on the way to ``root``."""
    resolved = root.parent.resolve()
    for parent in (resolved, *resolved.parents):
        info = parent.stat()
        owner_ok = info.st_uid in (0, os.getuid())
        writable_by_others = bool(info.st_mode & 0o022)
        shared = writable_by_others and not info.st_mode & stat.S_ISVTX
        if not owner_ok or shared:
            raise UnsafeCacheError(f"übergeordnetes Verzeichnis {parent} ist unsicher")


def _make_private(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise UnsafeCacheError("kein eigenes Verzeichnis")
    if info.st_mode & 0o077:
        os.chmod(path, 0o700)


def _reset_if_foreign(profile: Path) -> None:
    """A profile that is a symlink, foreign or ever was open is thrown away."""
    try:
        info = profile.lstat()
    except FileNotFoundError:
        return
    private = (
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.getuid()
        and not info.st_mode & 0o077
    )
    if not private:
        log.warning("Browser-Profil %s war nicht privat, wird neu angelegt", profile)
        _remove(profile)


def _remove(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink(missing_ok=True)
    else:
        shutil.rmtree(path)
