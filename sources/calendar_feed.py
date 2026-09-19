"""Upcoming events from a Google Calendar secret iCal (.ics) URL.

Get the URL from: Google Calendar -> Settings -> Settings for my calendars ->
<calendar> -> Integrate calendar -> "Secret address in iCal format".

Run standalone for debugging:  python -m sources.calendar_feed
"""

import logging
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List

import icalendar
import recurring_ical_events
import requests

import config

log = logging.getLogger(__name__)

# Day labels for the agenda sections, indexed by how many days away they are.
DAY_LABELS = {0: "Vandaag", 1: "Morgen"}


def day_offset(start: Any) -> int:
    """Days between today and an event start: 0 is today, 1 is tomorrow."""
    start_date = start.date() if isinstance(start, datetime) else start
    return (start_date - datetime.now().date()).days


def format_event_clock(start: Any, all_day: bool) -> str:
    """The clock time shown next to an event, in Dutch.

    Just the time ("09:30"): which day it is comes from the section the event is
    drawn under, so repeating it per row would be noise. All-day events have no
    clock time, so they say so.
    """
    if all_day or not isinstance(start, datetime):
        return "Hele dag"
    return start.strftime("%H:%M")


def _as_datetime(value: Any, tzinfo) -> datetime:
    """Normalise a DTSTART (date or datetime) to an aware datetime for sorting."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=tzinfo)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=tzinfo)
    raise TypeError(f"unsupported DTSTART type: {type(value)!r}")


def get_events(
    ics_url: str = None,
    count: int = None,
    lookahead_days: int = None,
) -> Dict[str, Any]:
    """Fetch, expand and return the next `count` upcoming events.

    Never raises. On failure returns {"events": [], "ok": False, "message": ...}.
    """
    ics_url = config.GOOGLE_CALENDAR_ICS_URL if ics_url is None else ics_url
    count = config.CALENDAR_EVENT_COUNT if count is None else count
    lookahead_days = (
        config.CALENDAR_LOOKAHEAD_DAYS if lookahead_days is None else lookahead_days
    )

    if not ics_url or ics_url.startswith("replace-with"):
        log.warning("No GOOGLE_CALENDAR_ICS_URL configured")
        return {"events": [], "ok": False, "message": "Agenda niet ingesteld"}

    try:
        response = requests.get(ics_url, timeout=config.HTTP_TIMEOUT)
        response.raise_for_status()
        calendar = icalendar.Calendar.from_ical(response.content)

        now = datetime.now().astimezone()
        local_tz = now.tzinfo
        window_end = (now + timedelta(days=lookahead_days)).replace(
            hour=23, minute=59, second=59, microsecond=0
        )

        # Expands recurring events into concrete occurrences inside the window.
        occurrences = recurring_ical_events.of(calendar).between(now, window_end)

        events: List[Dict[str, Any]] = []
        for occurrence in occurrences:
            raw_start = occurrence["DTSTART"].dt
            all_day = not isinstance(raw_start, datetime)
            start = _as_datetime(raw_start, local_tz)
            # An all-day event earlier today is still "today", but a timed event
            # that already started is in the past and not worth showing.
            if not all_day and start < now:
                continue
            events.append(
                {
                    "title": str(occurrence.get("SUMMARY", "(geen titel)")).strip(),
                    "start": start,
                    "all_day": all_day,
                }
            )

        events.sort(key=lambda item: (item["start"], item["title"]))
        return {"events": events[:count], "ok": True, "message": ""}
    except Exception as exc:  # noqa: BLE001 - deliberate catch-all
        log.warning("Calendar fetch failed: %s", exc)
        return {"events": [], "ok": False, "message": "Agenda niet beschikbaar"}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = get_events()
    print(f"ok={result['ok']} message={result['message']!r}")
    for event in result["events"]:
        label = DAY_LABELS.get(day_offset(event["start"]), "later")
        clock = format_event_clock(event["start"], event["all_day"])
        print(f"  {label:<8} {clock:<9} {event['title']}")
