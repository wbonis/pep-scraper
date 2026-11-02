"""Domain types."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

EventKind = Literal["shift", "free", "absence"]


@dataclass(frozen=True, slots=True)
class RosterEvent:
    """One calendar entry from the PEP roster.

    All-day events use ``date`` for start/end (end exclusive),
    timed events use naive local ``datetime``.
    """

    uid: str
    summary: str
    description: str
    start: date | datetime
    end: date | datetime
    all_day: bool
    kind: EventKind = "shift"
    code: str = ""
    color: str | None = None
    icon: str | None = None
