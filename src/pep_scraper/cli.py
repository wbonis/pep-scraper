"""Einstieg: Dienstplan holen, ICS schreiben, optional nach Yuvomi übertragen."""

import argparse
import json
import logging
import os
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from .config import Config, ConfigError, YuvomiConfig, load_config
from .fetch import FetchError, LoginError, PasswordExpiredError, fetch_dashboard
from .files import write_private_atomic
from .ics import build_calendar
from .models import RosterEvent
from .naming import NameEntry, NamesError, apply_names, load_names
from .new_codes import append_codes, unknown_codes
from .parser import ParseError, parse_dashboard
from .rules import apply_rules
from .settings import load_settings
from .state import load_tracked_types, save_tracked_types
from .yuvomi_client import YuvomiClient, YuvomiError
from .yuvomi_sync import ScheduleClient, SyncResult, SyncSettings, sync_schedule

log = logging.getLogger("pep_scraper")

EXIT_OK = 0
EXIT_CONFIG = 1  # .env fehlt oder ist falsch
EXIT_LOGIN = 2  # Kennung/Kennwort falsch, Captcha, 2FA, Konto gesperrt
EXIT_FETCH = 3  # Netz, LOGA-Wartung, Dienstplan nicht geladen
EXIT_PARSE = 4  # LOGA liefert ein unbekanntes Format
EXIT_YUVOMI = 5  # Übertragung nach Yuvomi fehlgeschlagen
EXIT_PASSWORD = 6  # LOGA verlangt ein neues Kennwort

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
        names = load_names(cfg.names_file)
        settings = load_settings(cfg.names_file)
    except NamesError as exc:
        log.error("Namensdatei: %s", exc)
        return EXIT_CONFIG
    try:
        payload = fetcher(cfg)
    except PasswordExpiredError as exc:
        log.error("Kennwort abgelaufen: %s", exc)
        return EXIT_PASSWORD
    except LoginError as exc:
        log.error("Anmeldung fehlgeschlagen: %s", exc)
        return EXIT_LOGIN
    except FetchError as exc:
        log.error("Abruf fehlgeschlagen: %s", exc)
        return EXIT_FETCH
    try:
        parsed = parse_dashboard(payload)
    except ParseError as exc:
        log.error("Unerwartetes Dienstplan-Format: %s", exc)
        return EXIT_PARSE
    if settings.add_new_codes:
        _add_new_codes(cfg.names_file, parsed, names, dry_run)
    events = apply_names(apply_rules(parsed, settings), names)
    write_private_atomic(cfg.output, build_calendar(events, cfg.tz_name))
    log.info("%d Einträge nach %s geschrieben", len(events), cfg.output)
    if cfg.yuvomi is None:
        return EXIT_OK
    return _sync_yuvomi(cfg.yuvomi, events, dry_run, client_factory, frozenset(names))


def _add_new_codes(
    path: Path,
    events: tuple[RosterEvent, ...],
    names: Mapping[str, NameEntry],
    dry_run: bool,
) -> None:
    """Unknown LOGA codes go into schichten.toml; a failure never stops the run."""
    new = unknown_codes(events, names)
    if not new:
        return
    codes = ", ".join(repr(code) for code, _ in new)
    if dry_run:
        log.info("Probelauf: neue Dienstcodes nicht in %s eingetragen: %s", path, codes)
        return
    try:
        append_codes(path, new, today=date.today())
    except (OSError, ValueError) as exc:  # incl. TOML and encoding errors
        log.warning("Neue Dienstcodes nicht in %s eingetragen: %s", path, exc)
        return
    log.info("Neue Dienstcodes in %s eingetragen: %s", path, codes)


def _sync_yuvomi(
    cfg: YuvomiConfig,
    events: tuple[RosterEvent, ...],
    dry_run: bool,
    client_factory: ClientFactory,
    named: frozenset[str] = frozenset(),
) -> int:
    settings = SyncSettings(
        user_id=cfg.user_id, absences=cfg.absences, shown_absences=named
    )
    tracked = load_tracked_types(cfg.state_file, cfg.base_url)

    def remember(types: dict[int, str]) -> None:
        save_tracked_types(cfg.state_file, cfg.base_url, types)

    try:
        with client_factory(cfg) as client:
            result = sync_schedule(
                events, client, settings, dry_run, tracked, on_tracked_change=remember
            )
    except YuvomiError as exc:
        log.error("Yuvomi-Übertragung fehlgeschlagen: %s", exc)
        return EXIT_YUVOMI
    if not dry_run and dict(result.tracked_types) != tracked:
        remember(dict(result.tracked_types))
    _log_summary(result, dry_run)
    return EXIT_OK


def _log_summary(result: SyncResult, dry_run: bool) -> None:
    log.info(
        "Yuvomi%s: %d Schichttypen angelegt, %d umbenannt, %d entfernt; "
        "%d Tage gesetzt, %d entfernt; %d Zusatzdienste angelegt, %d entfernt",
        " (Probelauf)" if dry_run else "",
        result.created_types,
        result.updated_types,
        result.removed_types,
        result.updated_days,
        result.deleted_days,
        result.added_extras,
        result.deleted_extras,
    )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LOGA3-PEP-Dienstplan als ICS exportieren und optional "
        "nach Yuvomi übertragen",
        epilog="Exit-Codes: 0 ok, 1 Konfiguration, 2 Anmeldung, 3 Abruf, "
        "4 Format, 5 Yuvomi, 6 Kennwort abgelaufen",
    )
    parser.add_argument(
        "--env-file", default=".env", help="Pfad zur .env (Standard: ./.env)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Yuvomi-Änderungen nur anzeigen, nichts schreiben",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--save-json",
        metavar="DATEI",
        help="LOGA-Antwort nach erfolgreichem Abruf hier speichern (0600)",
    )
    source.add_argument(
        "--from-json",
        metavar="DATEI",
        help="ohne LOGA-Anmeldung eine mit --save-json gespeicherte Antwort nutzen",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="ausführliche Ausgabe (Debug)"
    )
    return parser.parse_args(argv)


STALE_HOURS = 24


def _fetcher(args: argparse.Namespace) -> Fetcher:
    if args.from_json:
        return _from_file(Path(args.from_json), warn_if_stale=not args.dry_run)
    if args.save_json:
        return _saving(fetch_dashboard, Path(args.save_json))
    return fetch_dashboard


def _from_file(path: Path, warn_if_stale: bool) -> Fetcher:
    def load(_cfg: Config) -> dict[str, Any]:
        log.info("lese LOGA-Antwort aus %s (keine Anmeldung)", path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            age_hours = int((time.time() - path.stat().st_mtime) // 3600)
        except (OSError, ValueError) as exc:
            raise FetchError(f"{path} nicht lesbar: {exc}") from exc
        if not isinstance(data, dict):
            raise FetchError(f"{path} enthält kein JSON-Objekt")
        if warn_if_stale and age_hours >= STALE_HOURS:
            log.warning(
                "%s ist %d Stunden alt - Yuvomi bekommt diesen alten Stand",
                path,
                age_hours,
            )
        return data

    return load


def _saving(fetcher: Fetcher, path: Path) -> Fetcher:
    def fetch_and_save(cfg: Config) -> dict[str, Any]:
        payload = fetcher(cfg)
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        try:
            write_private_atomic(path, text.encode("utf-8"))
        except OSError as exc:  # saving is extra, the run goes on
            log.warning("LOGA-Antwort nicht gespeichert: %s", exc)
            return payload
        log.info("LOGA-Antwort in %s gespeichert", path)
        return payload

    return fetch_and_save


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
        log.error("Konfiguration: %s", exc)
        return EXIT_CONFIG
    return run(cfg, fetcher=_fetcher(args), dry_run=args.dry_run)
