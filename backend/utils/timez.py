# backend/utils/timez.py
"""
Time utilities for period classification and edit-window checks.

Why this file exists:
- Provide a single source of truth for month status (past/current/future)
  in the organization timezone.
- Provide a reusable guard to block writes on past periods.

Policy & assumptions:
- DB stores timestamps in UTC.
- UI renders in the organization's timezone.
- Editing window closes at 00:00 on the 1st day of the next month (org TZ).
- Organization timezone is fixed (no detection): "Europe/Warsaw".
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

# ---- Organization timezone (fixed) ---------------------------------------------
ORG_TZ = "Europe/Warsaw"  # single source of truth


def now_utc() -> datetime:
    """Return the current time in UTC with tzinfo=UTC."""
    # We keep UTC at DB/audit level; conversions happen at the edges (UI or serializers).
    return datetime.now(tz=ZoneInfo("UTC"))


def get_period_status(year: int, month: int) -> str:
    """
    Compute 'past' | 'current' | 'future' in the organization timezone.

    How it works:
    - Build 'period_start' (1st day 00:00) in ORG_TZ.
    - Build 'period_end'   (1st day of next month 00:00) in ORG_TZ.
    - Compare 'now' in ORG_TZ against [start, end):
        now < start  -> 'future'
        start <= now < end -> 'current'
        now >= end   -> 'past'
    """
    tz = ZoneInfo(ORG_TZ)
    now_local = datetime.now(tz)

    # Start of this month in org tz
    period_start = datetime(year, month, 1, 0, 0, 0, tzinfo=tz)

    # Start of next month in org tz
    next_month = month + 1 if month < 12 else 1
    next_year = year + 1 if month == 12 else year
    period_end = datetime(next_year, next_month, 1, 0, 0, 0, tzinfo=tz)

    if now_local < period_start:
        return "future"
    if now_local >= period_end:
        return "past"
    return "current"


def is_period_closed(year: int, month: int) -> bool:
    """
    Return True if edits MUST be blocked for {year, month} (in ORG_TZ).

    Policy:
    - Editing closes exactly at 00:00 on the 1st day of the *next* month (ORG_TZ).
    - Use this guard in write endpoints to raise 403 'period_closed'.
    """
    return get_period_status(year, month) == "past"
