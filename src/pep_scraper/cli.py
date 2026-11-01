"""Entry point: fetch roster, write ICS."""

import argparse
import logging
import os
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from .config import Config, ConfigError, load_config
from .fetch import FetchError, LoginError, fetch_dashboard
from .ics import build_calendar
from .parser import ParseError, parse_dashboard

log = logging.getLogger("pep_scraper")

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_LOGIN = 2
EXIT_FETCH = 3
EXIT_PARSE = 4

Fetcher = Callable[[Config], dict[str, Any]]


def run(cfg: Config, fetcher: Fetcher) -> int:
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
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    file_env = {k: v for k, v in dotenv_values(args.env_file).items() if v is not None}
    try:
        cfg = load_config({**file_env, **os.environ})
    except ConfigError as exc:
        log.error("%s", exc)
        return EXIT_CONFIG
    return run(cfg, fetcher=fetch_dashboard)
