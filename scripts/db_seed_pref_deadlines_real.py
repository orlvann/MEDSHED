# scripts/db_seed_pref_deadlines_real.py
"""
Seed real-looking preference deadlines for shifted demo years.

We simulate:
- source 2023 -> target 2025
- source 2024 -> target 2026
- source 2025 -> target 2027

So we create deadlines for months:
- 2025-02 .. 2027-12

Deadline rule:
- For a given {year, month}, the deadline is the 15th day of the *previous* month
  at 23:59 in the organisation timezone (e.g. Europe/Warsaw), stored as UTC.

DEV ONLY: this script wipes all existing PreferenceDeadline rows.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.db.session import SessionLocal
from backend.models.orm.preference import PreferenceDeadline

# Target months in the *shifted* timeline:
# 2023 -> 2025, 2024 -> 2026, 2025 -> 2027
TARGET_START_YEAR = 2025
TARGET_START_MONTH = 2  # 2025-02 (first month with data after shifting)
TARGET_END_YEAR = 2027
TARGET_END_MONTH = 12  # 2027-12


ORG_TIMEZONE = "Europe/Warsaw"


def iter_year_months(start_year: int, start_month: int, end_year: int, end_month: int):
    """
    Generate (year, month) pairs from start to end inclusive.
    Example:
        (2024, 2) .. (2026, 12)
    """
    year = start_year
    month = start_month
    while (year < end_year) or (year == end_year and month <= end_month):
        yield year, month
        month += 1
        if month > 12:
            month = 1
            year += 1


def previous_month(year: int, month: int) -> tuple[int, int]:
    """
    Return (prev_year, prev_month) for the given year, month.
    Example:
        (2024, 2) -> (2024, 1)
        (2024, 1) -> (2023, 12)
    """
    if month > 1:
        return year, month - 1
    return year - 1, 12


def seed_deadlines(db: Session) -> None:
    """
    Wipe all existing deadlines and insert new ones according to the rule:
    - For each target (year, month) in the shifted demo range,
      deadline = 15th of the *previous* month at 23:59 org local time.
    """
    # 1) Delete existing deadlines (local dev only)
    db.execute(delete(PreferenceDeadline))
    db.commit()

    org_tz = ZoneInfo(ORG_TIMEZONE)
    utc_tz = ZoneInfo("UTC")

    rows: list[PreferenceDeadline] = []

    for year, month in iter_year_months(
        TARGET_START_YEAR,
        TARGET_START_MONTH,
        TARGET_END_YEAR,
        TARGET_END_MONTH,
    ):
        prev_year, prev_month = previous_month(year, month)

        # 15th of previous month at 23:59 in organisation timezone
        local_deadline = datetime(prev_year, prev_month, 15, 23, 59, 0, tzinfo=org_tz)
        deadline_utc = local_deadline.astimezone(utc_tz)

        row = PreferenceDeadline(
            year=year,
            month=month,
            deadline_utc=deadline_utc,
            org_timezone=ORG_TIMEZONE,
        )
        rows.append(row)

    db.add_all(rows)
    db.commit()

    print(
        f"Inserted {len(rows)} preference deadlines for demo timeline "
        f"{TARGET_START_YEAR}-{TARGET_START_MONTH:02d} "
        f"to {TARGET_END_YEAR}-{TARGET_END_MONTH:02d}."
    )


def main() -> None:
    db: Session = SessionLocal()
    try:
        seed_deadlines(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
