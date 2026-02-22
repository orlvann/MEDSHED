"""Build ICS (iCalendar) files for schedule exports (personal & team)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import List

from icalendar import Calendar, Event

from backend.utils.exporters import DoctorExportData, TeamExportData

_SHIFT_LABELS = {
    "onsite": "Dyzur stacjonarny",
    "oncall": "Dyzur pod telefonem",
}


def build_ics(data: DoctorExportData) -> bytes:
    """Return raw bytes of an ICS calendar for one doctor."""
    cal = Calendar()
    cal.add("prodid", "-//MEDSHED//Schedule Export//PL")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", f"MEDSHED - Dr. {data.first_name} {data.last_name}")
    cal.add("x-wr-timezone", data.org_timezone)

    now_utc = datetime.now(tz=timezone.utc)

    for asn in sorted(data.assignments, key=lambda a: (a["day"], a["shift_type"])):
        day = asn["day"]
        shift_type = asn["shift_type"]

        event = Event()
        event_date = date(data.year, data.month, day)
        event.add("dtstart", event_date)
        event.add("dtend", event_date + timedelta(days=1))

        label = _SHIFT_LABELS.get(shift_type, shift_type)
        event.add("summary", f"MEDSHED: {label}")

        uid = f"{data.year}-{data.month:02d}-{day:02d}-{shift_type}-{data.doctor_id}@medshed"
        event.add("uid", uid)
        event.add("dtstamp", now_utc)

        cal.add_component(event)

    return cal.to_ical()


def build_team_ics(data: TeamExportData) -> bytes:
    """Return raw bytes of an ICS calendar for the full team schedule."""
    cal = Calendar()
    cal.add("prodid", "-//MEDSHED//Schedule Export//PL")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", f"MEDSHED - Team Schedule")
    cal.add("x-wr-timezone", data.org_timezone)

    now_utc = datetime.now(tz=timezone.utc)

    for asn in sorted(data.assignments, key=lambda a: (a["day"], a["doctor_name"], a["shift_type"])):
        day = asn["day"]
        shift_type = asn["shift_type"]
        doctor_name = asn["doctor_name"]

        event = Event()
        event_date = date(data.year, data.month, day)
        event.add("dtstart", event_date)
        event.add("dtend", event_date + timedelta(days=1))

        label = _SHIFT_LABELS.get(shift_type, shift_type)
        event.add("summary", f"{doctor_name}: {label}")

        # doctor_name in UID to keep events unique per doctor
        safe_name = doctor_name.replace(" ", "_")
        uid = f"{data.year}-{data.month:02d}-{day:02d}-{shift_type}-{safe_name}@medshed"
        event.add("uid", uid)
        event.add("dtstamp", now_utc)

        cal.add_component(event)

    return cal.to_ical()


def build_team_feed_ics(
    *,
    org_timezone: str,
    assignments: List[dict],
) -> bytes:
    """Build a subscription-friendly ICS for the full team spanning multiple months.

    Each assignment dict: {"year": int, "month": int, "day": int, "shift_type": str, "doctor_name": str}.
    Adds REFRESH-INTERVAL / X-PUBLISHED-TTL so calendar apps re-poll every 4 hours.
    """
    cal = Calendar()
    cal.add("prodid", "-//MEDSHED//Calendar Feed//PL")
    cal.add("version", "2.0")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", "MEDSHED - Team Schedule")
    cal.add("x-wr-timezone", org_timezone)
    cal.add("refresh-interval;value=duration", "PT4H")
    cal.add("x-published-ttl", "PT4H")

    now_utc = datetime.now(tz=timezone.utc)

    for asn in sorted(assignments, key=lambda a: (a["year"], a["month"], a["day"], a["doctor_name"], a["shift_type"])):
        y = asn["year"]
        m = asn["month"]
        d = asn["day"]
        shift_type = asn["shift_type"]
        doctor_name = asn["doctor_name"]

        event = Event()
        event_date = date(y, m, d)
        event.add("dtstart", event_date)
        event.add("dtend", event_date + timedelta(days=1))

        label = _SHIFT_LABELS.get(shift_type, shift_type)
        event.add("summary", f"{doctor_name}: {label}")

        safe_name = doctor_name.replace(" ", "_")
        uid = f"{y}-{m:02d}-{d:02d}-{shift_type}-{safe_name}@medshed"
        event.add("uid", uid)
        event.add("dtstamp", now_utc)

        cal.add_component(event)

    return cal.to_ical()


def build_feed_ics(
    *,
    doctor_id: int,
    first_name: str,
    last_name: str,
    org_timezone: str,
    assignments: List[dict],
) -> bytes:
    """Build a subscription-friendly ICS spanning multiple months.

    Each assignment dict: {"year": int, "month": int, "day": int, "shift_type": str}.
    Adds REFRESH-INTERVAL / X-PUBLISHED-TTL so calendar apps re-poll every 4 hours.
    """
    cal = Calendar()
    cal.add("prodid", "-//MEDSHED//Calendar Feed//PL")
    cal.add("version", "2.0")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", f"MEDSHED - Dr. {first_name} {last_name}")
    cal.add("x-wr-timezone", org_timezone)
    # Re-poll hints for calendar apps (RFC 7986 + Apple/Google extension)
    cal.add("refresh-interval;value=duration", "PT4H")
    cal.add("x-published-ttl", "PT4H")

    now_utc = datetime.now(tz=timezone.utc)

    for asn in sorted(assignments, key=lambda a: (a["year"], a["month"], a["day"], a["shift_type"])):
        y = asn["year"]
        m = asn["month"]
        d = asn["day"]
        shift_type = asn["shift_type"]

        event = Event()
        event_date = date(y, m, d)
        event.add("dtstart", event_date)
        event.add("dtend", event_date + timedelta(days=1))

        label = _SHIFT_LABELS.get(shift_type, shift_type)
        event.add("summary", f"MEDSHED: {label}")

        uid = f"{y}-{m:02d}-{d:02d}-{shift_type}-{doctor_id}@medshed"
        event.add("uid", uid)
        event.add("dtstamp", now_utc)

        cal.add_component(event)

    return cal.to_ical()
