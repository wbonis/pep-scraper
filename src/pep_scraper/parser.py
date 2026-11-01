"""Turn the LOGA3 ``loadShiftsDashboard`` JSON into roster events."""

import hashlib
import logging
from collections.abc import Iterator, Mapping
from datetime import date, datetime, timedelta
from typing import Any

from .models import RosterEvent

log = logging.getLogger(__name__)

PLAN_TYPES = frozenset({"SPEP_PLAN", "OPEP_PLAN"})
UID_DOMAIN = "pep-scraper"


class ParseError(ValueError):
    """Payload does not have the expected structure."""


def parse_dashboard(payload: Mapping[str, Any]) -> tuple[RosterEvent, ...]:
    events = payload.get("events")
    if not isinstance(events, list):
        raise ParseError("payload has no 'events' list")
    try:
        return tuple(ev for raw in events for ev in _parse_entry(raw))
    except (KeyError, TypeError, ValueError) as exc:
        raise ParseError(f"malformed entry: {exc!r}") from exc


def _parse_entry(raw: Mapping[str, Any]) -> Iterator[RosterEvent]:
    if raw.get("absence") is True:
        yield _absence(raw)
    elif raw.get("type") in PLAN_TYPES:
        for index, shift in enumerate(raw.get("shifts") or ()):
            yield _shift(raw, shift, index)
    else:
        log.warning(
            "skipping unknown entry type %r on %s", raw.get("type"), raw.get("date")
        )


def _absence(raw: Mapping[str, Any]) -> RosterEvent:
    day = date.fromisoformat(raw["date"])
    title = str(raw["title"])
    return RosterEvent(
        uid=_uid("absence", day.isoformat(), title),
        summary=title,
        description="Abwesenheit",
        start=day,
        end=day + timedelta(days=1),
        all_day=True,
        kind="absence",
        code=title,
    )


def _shift(raw: Mapping[str, Any], shift: Mapping[str, Any], index: int) -> RosterEvent:
    start = datetime.fromisoformat(shift["from"])
    end = datetime.fromisoformat(shift["to"])
    code = str(shift["code"])
    summary = f"{code} {shift['name']}".strip()
    uid = _uid("shift", raw["date"], code, str(index))
    description = str(raw.get("title", ""))
    color = _rgb_from_colorref(shift.get("color"))
    if start == end:
        day = start.date()
        return RosterEvent(
            uid=uid,
            summary=summary,
            description=description,
            start=day,
            end=day + timedelta(days=1),
            all_day=True,
            kind="free",
            code=code,
            color=color,
        )
    if end < start:  # night shift: LOGA keeps start date in 'to'
        end = end + timedelta(days=1)
    return RosterEvent(
        uid=uid,
        summary=summary,
        description=description,
        start=start,
        end=end,
        all_day=False,
        kind="shift",
        code=code,
        color=color,
    )


def _rgb_from_colorref(value: Any) -> str | None:
    """LOGA sends Windows COLORREF ints (0x00BBGGRR); return #RRGGBB."""
    if not isinstance(value, int) or not 0 <= value <= 0xFFFFFF:
        return None
    red, green, blue = value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF
    return f"#{red:02X}{green:02X}{blue:02X}"


def _uid(*parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{digest}@{UID_DOMAIN}"
