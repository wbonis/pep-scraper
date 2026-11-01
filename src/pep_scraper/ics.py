"""Render roster events as an iCalendar file."""

from collections.abc import Iterable
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event, Timezone

from .models import RosterEvent

CALENDAR_NAME = "Dienstplan PEP"
PRODID = "-//pep-scraper//LOGA3 PEP//DE"


def build_calendar(events: Iterable[RosterEvent], tz_name: str) -> bytes:
    tz = ZoneInfo(tz_name)
    stamp = datetime.now(UTC)
    cal = Calendar()
    cal.add("prodid", PRODID)
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", CALENDAR_NAME)
    cal.add("x-wr-timezone", tz_name)
    cal.add_component(Timezone.from_tzid(tz_name))
    for event in events:
        cal.add_component(_to_vevent(event, tz, stamp))
    return bytes(cal.to_ical())


def _to_vevent(event: RosterEvent, tz: ZoneInfo, stamp: datetime) -> Event:
    vevent = Event()
    vevent.add("uid", event.uid)
    vevent.add("dtstamp", stamp)
    vevent.add("summary", event.summary)
    if event.description:
        vevent.add("description", event.description)
    if event.all_day:
        vevent.add("dtstart", event.start)
        vevent.add("dtend", event.end)
        vevent.add("transp", "TRANSPARENT")
    else:
        vevent.add("dtstart", _localize(event.start, tz))
        vevent.add("dtend", _localize(event.end, tz))
    return vevent


def _localize(value: date | datetime, tz: ZoneInfo) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"Termin mit Uhrzeit braucht datetime, nicht {value!r}")
    return value.replace(tzinfo=tz)
