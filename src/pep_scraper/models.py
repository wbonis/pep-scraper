"""Domain types."""

from dataclasses import dataclass
from datetime import date, datetime


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
