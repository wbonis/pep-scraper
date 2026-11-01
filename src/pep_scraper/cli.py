"""Entry point: fetch roster, write ICS."""

import argparse
import logging
import os
import tempfile
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from .config import Config, ConfigError, YuvomiConfig, load_config
from .fetch import FetchError, LoginError, fetch_dashboard
from .ics import build_calendar
from .models import RosterEvent
from .parser import ParseError, parse_dashboard
from .yuvomi_client import YuvomiClient, YuvomiError
from .yuvomi_sync import ScheduleClient, SyncSettings, sync_schedule

log = logging.getLogger("pep_scraper")

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_LOGIN = 2
EXIT_FETCH = 3
EXIT_PARSE = 4
EXIT_YUVOMI = 5

Fetcher = Callable[[Config], dict[str, Any]]
ClientFactory = Callable[[YuvomiConfig], AbstractContextManager[ScheduleClient]]


def _open_yuvomi(cfg: YuvomiConfig) -> AbstractContextManager[ScheduleClient]:
    return YuvomiClient(cfg.base_url, cfg.api_key)


def run(
    cfg: Config,
    fetcher: Fetcher,
    dry_run: bool = False,
    client_factory: ClientFactory = _open_yuvomi,
) -> int:
    try:
        payload = fetcher(cfg)
    except LoginError as exc:
        log.error("login failed: %s", exc)
        return EXIT_LOGIN
    except FetchError as exc:
        log.error("fetch failed: %s", exc)
        return EXIT_FETCH
    try:
        events = parse_dashboard(payload)
    except ParseError as exc:
        log.error("unexpected roster format: %s", exc)
        return EXIT_PARSE
    _write_atomic(cfg.output, build_calendar(events, cfg.tz_name))
    log.info("wrote %d events to %s", len(events), cfg.output)
    if cfg.yuvomi is None:
        return EXIT_OK
    return _sync_yuvomi(cfg.yuvomi, events, dry_run, client_factory)


def _sync_yuvomi(
    cfg: YuvomiConfig,
    events: tuple[RosterEvent, ...],
    dry_run: bool,
    client_factory: ClientFactory,
) -> int:
    settings = SyncSettings(user_id=cfg.user_id, absences=cfg.absences)
    try:
        with client_factory(cfg) as client:
            result = sync_schedule(events, client, settings, dry_run=dry_run)
    except YuvomiError as exc:
        log.error("yuvomi sync failed: %s", exc)
        return EXIT_YUVOMI
    log.info(
        "yuvomi%s: %d shift types created, %d days set, %d days removed",
        " (dry-run)" if dry_run else "",
        result.created_types,
        result.updated_days,
        result.deleted_days,
    )
    return EXIT_OK


def _write_atomic(path: Path, data: bytes) -> None:
    """Write via a private (0600) temp file in the same dir, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as tmp:
        tmp.write(data)
    Path(tmp.name).replace(path)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export LOGA3 PEP roster as ICS")
    parser.add_argument(
        "--env-file", default=".env", help="path to .env (default: ./.env)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="show Yuvomi changes without writing"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not args.verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)
    file_env = {k: v for k, v in dotenv_values(args.env_file).items() if v is not None}
    try:
        cfg = load_config({**file_env, **os.environ})
    except ConfigError as exc:
        log.error("%s", exc)
        return EXIT_CONFIG
    return run(cfg, fetcher=fetch_dashboard, dry_run=args.dry_run)
