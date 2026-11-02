"""Roster rules from ``[einstellungen]``: holidays, credited work time, breaks.

All functions are pure: they return new events and never change their input.
"""

from collections.abc import Iterable
from dataclasses import replace
from datetime import date, datetime, timedelta

from .models import RosterEvent
from .naming import norm
from .settings import BreakRule, Credit, Settings

FREE_DAY = "Freier Tag"


def apply_rules(
    events: Iterable[RosterEvent], settings: Settings
) -> tuple[RosterEvent, ...]:
    result = tuple(events)
    if settings.holiday_rule:
        result = apply_holiday_rule(result, settings.holiday_titles)
    return apply_break(apply_credit(result, settings.credit), settings.pause)


def apply_holiday_rule(
    events: Iterable[RosterEvent], titles: frozenset[str]
) -> tuple[RosterEvent, ...]:
    """Holiday without a shift that day -> free day; with a shift -> dropped."""
    events = tuple(events)
    shift_days = {_day(e) for e in events if e.kind in ("shift", "free")}
    result: list[RosterEvent] = []
    for event in events:
        if not (event.kind == "absence" and norm(event.code) in titles):
            result.append(event)
        elif _day(event) not in shift_days:
            free = replace(event, kind="free", summary=FREE_DAY, description=event.code)
            result.append(free)
    return tuple(result)


def apply_credit(
    events: Iterable[RosterEvent], credit: Credit
) -> tuple[RosterEvent, ...]:
    """Credit work time for listed all-day entries (Arbeitszeitäquivalent)."""
    return tuple(_credited(e, credit) for e in events)


def _credited(event: RosterEvent, credit: Credit) -> RosterEvent:
    if not event.all_day or norm(event.code) not in credit.titles:
        return event
    if credit.mode == "info":
        return _with_note(event, f"Gutschrift {_hours(credit.hours)} Std.")
    start = datetime.combine(_day(event), credit.start)
    return replace(event, start=start, end=start + credit.hours, all_day=False)


def apply_break(
    events: Iterable[RosterEvent], rule: BreakRule
) -> tuple[RosterEvent, ...]:
    """Deduct the break from the end of each long enough shift."""
    return tuple(_with_break(e, rule) for e in events)


def _with_break(event: RosterEvent, rule: BreakRule) -> RosterEvent:
    pause = timedelta(minutes=rule.minutes)
    if event.kind != "shift" or event.all_day or not pause:
        return event
    if not (isinstance(event.start, datetime) and isinstance(event.end, datetime)):
        return event
    length = event.end - event.start
    if length <= rule.min_length or length <= pause:
        return event
    if rule.mode == "info":
        return _with_note(event, f"Netto {_hours(length - pause)} Std.")
    return replace(event, end=event.end - pause)


def _with_note(event: RosterEvent, note: str) -> RosterEvent:
    text = f"{event.description}\n{note}" if event.description else note
    return replace(event, description=text)


def _hours(value: timedelta) -> str:
    minutes = round(value.total_seconds() / 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


def _day(event: RosterEvent) -> date:
    if isinstance(event.start, datetime):
        return event.start.date()
    return event.start
