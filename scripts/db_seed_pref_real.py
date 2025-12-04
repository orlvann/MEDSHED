# scripts/db_seed_pref_real.py
"""
Seed real monthly preferences from Excel files.

Flow:
- For each Excel file (e.g. 2023_02_devon.xlsx):
  - Parse year, month and alias from the filename.
  - Map alias -> (first_name, last_name) and find doctor_id in DB.
  - Read onsite/on-call preferences from Excel:
        CHCĘ / CHCE      -> preferred_*_days
        NIE MOGĘ / MOGE  -> unavailable_*_days
        MOGĘ / ""        -> implicitly available (not stored).
  - Read an optional comment from the bottom of the sheet (row starting with 'KOMENTARZ').
  - Upsert PreferenceWorking for (doctor_id, year, month).
  - Create a PreferenceVersion snapshot with JSON payload.
  - Create/update PreferencePointer to point at this version.

Important:
- Run AFTER seeding doctors (so doctors table is already filled).
- Excel structure is assumed as on the screenshot:
  A: day number (1..31)
  B: day of week (text, ignored here)
  C: "Dyżur" with values like "MOGĘ", "NIE MOGĘ", "CHCĘ"
  D: "Poddyżur" (on-call) with similar values.
  Last row(s): a comment, e.g. "KOMENTARZ: 4? ;) 3 środy i coś, ferie w pierwszym tygodniu".
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openpyxl import load_workbook
from sqlalchemy import select

from backend.db.session import SessionLocal
from backend.models.orm.doctor import Doctor
from backend.models.orm.preference import (
    PreferencePointer,
    PreferenceVersion,
    PreferenceWorking,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Directory with Excel files. Adjust if your path is different.
EXCEL_DIR = Path("data/preferences_excel")

# Map from alias used in filenames -> (first_name, last_name) in DB.
# Example filename: 2023_02_devon.xlsx  -> alias = "devon".
# IMPORTANT: keys MUST be lowercase, because we .lower() the alias from filename.
ALIAS_TO_NAME: Dict[str, Tuple[str, str]] = {
    "devon": ("Brad", "Devon"),
    "grizzly": ("Rick", "Grizzly"),
    "hamster": ("Anna", "Hamster"),
    "jedi": ("Martin", "Jedi"),
    "kolton": ("Jake", "Kolton"),
    "lukewood": ("Ralph", "Lukewood"),
    "router": ("Mark", "Router"),
    "skipperp": ("Paul", "Skipper"),
    "skipperw": ("William", "Skipper"),
    "streeter": ("Anna", "Streeter"),
    "sussman": ("Paul", "Sussman"),
    "tacker": ("Alice", "Tacker"),
    # Add more if needed.
}


def map_year_for_seed(raw_year: int) -> int:
    """Map original Excel year to target demo year.

    Excel files use years 2023–2025.
    In DB we want them shifted by +2 years:
      2023 -> 2025
      2024 -> 2026
      2025 -> 2027

    If some unexpected year appears, we fail fast.
    """
    mapping = {
        2023: 2025,
        2024: 2026,
        2025: 2027,
    }
    if raw_year not in mapping:
        raise ValueError(f"Unsupported source year {raw_year} in Excel file – expected 2023–2025.")
    return mapping[raw_year]


# ---------------------------------------------------------------------------
# Helpers for parsing and Excel reading
# ---------------------------------------------------------------------------


def parse_year_month_alias(path: Path) -> Tuple[int, int, str]:
    """
    Extract year, month, alias from filename like '2023_02_devon.xlsx'.

    Returns:
        (year, month, alias_lower)
    """
    name = path.stem  # e.g. "2023_02_devon"
    parts = name.split("_")
    if len(parts) < 3:
        raise ValueError(f"Filename {path.name!r} does not match 'YYYY_MM_alias.xlsx' pattern")

    year_str, month_str, alias = parts[0], parts[1], "_".join(parts[2:])
    year = int(year_str)
    month = int(month_str)
    return year, month, alias.lower()


def normalize_str(value: Any) -> str:
    """
    Convert Excel cell value to UPPERCASE string without leading/trailing spaces.

    This is used to normalize text like " ChcĘ " -> "CHCĘ".
    """
    if value is None:
        return ""
    return str(value).strip().upper()


def to_int_day(value: Any) -> Optional[int]:
    """
    Convert Excel cell value from column A to an integer day (1..31).

    We handle a few common cases:
    - int (e.g. 1)
    - float (e.g. 1.0)
    - string digits (e.g. "1")
    If it cannot be converted to a valid day, return None.
    """
    if value is None:
        return None

    # If it's already int, just return it.
    if isinstance(value, int):
        return value

    # If it's a float like 1.0, we try to cast if it's "integer-like".
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return None

    # If it's a string with digits, try to parse.
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)

    # Any other type is not supported as a day.
    return None


def is_preferred(value_norm: str) -> bool:
    """
    Return True if normalized cell value means "preferred" (CHCĘ/CHCE).
    """
    # We accept both CHCĘ and CHCE, so we just check the prefix.
    return value_norm.startswith("CHC")


def is_unavailable(value_norm: str) -> bool:
    """
    Return True if normalized cell value means "unavailable" (NIE MOGĘ/MOGE).
    """
    # We accept both NIE MOGĘ and NIE MOGE.
    return value_norm.startswith("NIE MOG")


def load_day_lists_from_excel(
    path: Path,
) -> Tuple[List[int], List[int], List[int], List[int], Optional[str]]:
    """
    Read Excel file and return four lists of day numbers (1..31)
    plus an optional comment.

    Returns:
        (
            preferred_onsite_days,
            unavailable_onsite_days,
            preferred_oncall_days,
            unavailable_oncall_days,
            comment,  # full text of the comment row or None
        )

    Rules:
    - Column C ("Dyżur" / onsite):
        CHCĘ / CHCE          -> preferred_onsite_days
        NIE MOGĘ / NIE MOGE  -> unavailable_onsite_days
        MOGĘ / ""            -> ignored (means "normally available")
    - Column D ("Poddyżur" / on-call):
        CHCĘ / CHCE          -> preferred_oncall_days
        NIE MOGĘ / NIE MOGE  -> unavailable_oncall_days
        MOGĘ / ""            -> ignored
    """

    wb = load_workbook(path, data_only=True)
    ws = wb.active
    assert ws is not None, "Workbook has no active worksheet"

    preferred_onsite_days: List[int] = []
    unavailable_onsite_days: List[int] = []
    preferred_oncall_days: List[int] = []
    unavailable_oncall_days: List[int] = []
    comment: Optional[str] = None

    # First pass: read rows with days (1..31)
    for row_idx in range(2, ws.max_row + 1):
        raw_day = ws[f"A{row_idx}"].value
        day = to_int_day(raw_day)
        if day is None:
            # Skip rows that do not have a valid day number.
            continue

        onsite_value = normalize_str(ws[f"C{row_idx}"].value)
        oncall_value = normalize_str(ws[f"D{row_idx}"].value)

        # Onsite column (C)
        if is_preferred(onsite_value):
            preferred_onsite_days.append(day)
        elif is_unavailable(onsite_value):
            unavailable_onsite_days.append(day)
        # "MOGĘ" and "" are treated as neutral -> not stored.

        # On-call column (D)
        if is_preferred(oncall_value):
            preferred_oncall_days.append(day)
        elif is_unavailable(oncall_value):
            unavailable_oncall_days.append(day)
        # "MOGĘ" and "" again mean "available" -> not stored.

    # Second pass: look for an explicit comment row from the bottom.
    # We only accept rows where the text starts with 'KOMENTARZ'.
    for row_idx in range(ws.max_row, 1, -1):
        # We try column B first (more likely for text), then A.
        raw = ws[f"B{row_idx}"].value or ws[f"A{row_idx}"].value
        if raw is None:
            # Empty cell → skip
            continue

        text = str(raw).strip()
        if not text:
            # Only spaces → skip
            continue

        upper = text.upper()
        if not upper.startswith("KOMENTARZ"):
            # Not a comment marker (e.g. 'piątek') → skip
            continue

        # Strip the 'KOMENTARZ' word and an optional ':' that follows.
        rest = text[len("KOMENTARZ") :].lstrip()
        if rest.startswith(":"):
            rest = rest[1:].lstrip()

        # If there is no text after the marker → treat as no comment.
        comment = rest or None
        break

    return (
        preferred_onsite_days,
        unavailable_onsite_days,
        preferred_oncall_days,
        unavailable_oncall_days,
        comment,
    )


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def get_doctor_id_by_alias(session, alias: str) -> int:
    """
    Resolve doctor_id from alias using ALIAS_TO_NAME and the doctors table.

    Steps:
    - Find (first_name, last_name) for given alias.
    - Query doctors table for this pair.
    - Return doctor's id.
    """
    if alias not in ALIAS_TO_NAME:
        raise KeyError(f"Alias {alias!r} not found in ALIAS_TO_NAME mapping")

    first_name, last_name = ALIAS_TO_NAME[alias]

    stmt = select(Doctor).where(Doctor.first_name == first_name).where(Doctor.last_name == last_name)
    doctor = session.execute(stmt).scalar_one_or_none()

    if doctor is None:
        raise RuntimeError(f"Doctor not found in DB for alias {alias!r} " f"-> ({first_name!r}, {last_name!r})")

    return doctor.id


def get_or_create_working(
    session,
    doctor_id: int,
    year: int,
    month: int,
) -> PreferenceWorking:
    """
    Get existing PreferenceWorking row for (doctor_id, year, month)
    or create a new one if it does not exist.

    Newly created row has:
    - lock_version = 1
    - empty lists and default counters.
    """
    stmt = (
        select(PreferenceWorking)
        .where(PreferenceWorking.doctor_id == doctor_id)
        .where(PreferenceWorking.year == year)
        .where(PreferenceWorking.month == month)
    )
    existing = session.execute(stmt).scalar_one_or_none()

    if existing is not None:
        return existing

    working = PreferenceWorking(
        doctor_id=doctor_id,
        year=year,
        month=month,
        lock_version=1,
    )
    session.add(working)
    session.flush()  # assign ID
    print("  created new PreferenceWorking row")
    return working


def build_payload_from_working(working: PreferenceWorking) -> Dict[str, Any]:
    """
    Build JSON payload for PreferenceVersion from PreferenceWorking row.

    Important:
    - Datetimes are converted to ISO strings so they can be stored in JSON.
    - This payload shape should roughly match the DTO for preferences.
    """
    return {
        "doctor_id": working.doctor_id,
        "year": working.year,
        "month": working.month,
        "unavailable_onsite_days": working.unavailable_onsite_days or [],
        "unavailable_oncall_days": working.unavailable_oncall_days or [],
        "preferred_onsite_days": working.preferred_onsite_days or [],
        "preferred_oncall_days": working.preferred_oncall_days or [],
        "min_onsite_total": working.min_onsite_total,
        "max_onsite_total": working.max_onsite_total,
        "target_onsite_total": working.target_onsite_total,
        "min_oncall_total": working.min_oncall_total,
        "max_oncall_total": working.max_oncall_total,
        "target_oncall_total": working.target_oncall_total,
        "max_onsite_weekends": working.max_onsite_weekends,
        "target_onsite_weekends": working.target_onsite_weekends,
        "max_oncall_weekends": working.max_oncall_weekends,
        "target_oncall_weekends": working.target_oncall_weekends,
        "preferred_onsite_weekdays": working.preferred_onsite_weekdays or [],
        "preferred_oncall_weekdays": working.preferred_oncall_weekdays or [],
        "avoid_onsite_weekdays": working.avoid_onsite_weekdays or [],
        "avoid_oncall_weekdays": working.avoid_oncall_weekdays or [],
        "allow_weekend_consecutive_onsite_oncall": working.allow_weekend_consecutive_onsite_oncall,
        "preferred_partners": working.preferred_partners or [],
        "comments": working.comments,
        "last_saved_at": working.last_saved_at.isoformat() if working.last_saved_at else None,
        "last_saved_by_user_id": working.last_saved_by_user_id,
        "last_saved_by_role": working.last_saved_by_role,
        "last_admin_note": working.last_admin_note,
    }


def upsert_pointer(
    session,
    doctor_id: int,
    year: int,
    month: int,
    version_id: int,
    submitted_at: datetime,
) -> None:
    """
    Create or update PreferencePointer for (doctor_id, year, month)
    so that it points to the given version_id.

    For seed we treat this as if doctor has "submitted" preferences.
    """
    stmt = (
        select(PreferencePointer)
        .where(PreferencePointer.doctor_id == doctor_id)
        .where(PreferencePointer.year == year)
        .where(PreferencePointer.month == month)
    )
    pointer = session.execute(stmt).scalar_one_or_none()

    if pointer is None:
        pointer = PreferencePointer(
            doctor_id=doctor_id,
            year=year,
            month=month,
        )
        session.add(pointer)

    pointer.current_version_id = version_id
    pointer.submitted_at = submitted_at
    # For seed we store fake "system/admin" submitter.
    pointer.submitted_by_user_id = 0
    pointer.submitted_by_role = "admin"


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------


def process_single_file(session, path: Path) -> None:
    """
    Process one Excel file:
    - parse metadata from filename
    - map original Excel year to target demo year (2023->2025, 2024->2026, 2025->2027)
    - resolve doctor_id
    - read four day lists + comment from Excel
    - upsert working
    - create version + pointer
    """
    raw_year, month, alias = parse_year_month_alias(path)
    year = map_year_for_seed(raw_year)
    doctor_id = get_doctor_id_by_alias(session, alias)

    (
        preferred_onsite_days,
        unavailable_onsite_days,
        preferred_oncall_days,
        unavailable_oncall_days,
        comment,
    ) = load_day_lists_from_excel(path)

    print(
        f"[FILE] {path.name} -> raw_year={raw_year}, mapped_year={year}, "
        f"month={month}, alias={alias}, doctor_id={doctor_id}"
    )
    print(f"  preferred_onsite_days  = {preferred_onsite_days}")
    print(f"  unavailable_onsite_days= {unavailable_onsite_days}")
    print(f"  preferred_oncall_days  = {preferred_oncall_days}")
    print(f"  unavailable_oncall_days= {unavailable_oncall_days}")
    print(f"  comment                = {comment!r}")

    # 1) Upsert working row
    working = get_or_create_working(session, doctor_id, year, month)

    # Update working row with lists from Excel.
    working.preferred_onsite_days = preferred_onsite_days
    working.unavailable_onsite_days = unavailable_onsite_days
    working.preferred_oncall_days = preferred_oncall_days
    working.unavailable_oncall_days = unavailable_oncall_days

    # Store comment (can be None if not present).
    working.comments = comment

    # We can also set last_saved_* audit fields for clarity.
    now = datetime.utcnow()
    working.last_saved_at = now
    working.last_saved_by_user_id = 0
    working.last_saved_by_role = "admin"

    # 2) Create new version with full JSON payload
    payload = build_payload_from_working(working)

    new_version = PreferenceVersion(
        doctor_id=doctor_id,
        year=year,
        month=month,
        kind="checkpoint",  # imported checkpoint
        payload=payload,  # this is the ONLY data field in versions
        created_at=now,
        created_by_user_id=0,
        created_by_role="admin",
        note="Seeded from Excel file",
    )
    session.add(new_version)
    session.flush()  # so new_version.id is available

    print(f"  created PreferenceVersion id={new_version.id}")

    # 3) Update pointer to point to this version
    upsert_pointer(session, doctor_id, year, month, new_version.id, now)


def main() -> None:
    """
    Entry point of the script.
    - Creates DB session.
    - Iterates over all .xlsx files in EXCEL_DIR.
    - Processes each file and commits at the end.
    """
    if not EXCEL_DIR.exists():
        raise RuntimeError(f"Directory {EXCEL_DIR!r} does not exist. Adjust EXCEL_DIR in the script.")

    excel_files = sorted(EXCEL_DIR.glob("*.xlsx"))
    if not excel_files:
        print(f"No .xlsx files found in {EXCEL_DIR}")
        return

    session = SessionLocal()
    try:
        for path in excel_files:
            process_single_file(session, path)

        # Commit all changes once at the end.
        session.commit()
        print("All files processed and committed.")
    except Exception as exc:
        # In case of error we rollback to keep DB consistent.
        session.rollback()
        print(f"ERROR: {exc}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
