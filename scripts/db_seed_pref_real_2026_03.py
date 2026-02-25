# scripts/db_seed_pref_real_2026_03.py
"""
Seed real monthly preferences from Excel files for March 2026.

Expected filename format:
    2026_03_alias.xlsx

What this script does (safe import strategy):
1) Upsert PreferenceWorking for (doctor_id, 2026, 3) and overwrite it with Excel data.
2) Create a NEW PreferenceVersion checkpoint (append-only history).
3) Upsert PreferencePointer for (doctor_id, 2026, 3) and point it to the new version.

Why we do it this way:
- PreferenceWorking is an editable buffer (autosave form state).
- PreferenceVersion is the immutable history store.
- PreferencePointer tells which version is "current".
- We do NOT delete anything to avoid breaking history/audit and FK relations.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openpyxl import load_workbook
from sqlalchemy import select

from backend.db.session import SessionLocal
from backend.models.orm.doctor import Doctor
from backend.models.orm.preference import PreferencePointer, PreferenceVersion, PreferenceWorking

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

EXCEL_DIR = Path("data/preferences_excel")

TARGET_YEAR = 2026
TARGET_MONTH = 3

# IMPORTANT: keys MUST be lowercase, because we lower() the alias from filename.
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
}

ADMIN_USER_ID = 0
ADMIN_ROLE = "admin"

# ---------------------------------------------------------------------------
# Helpers: filename parsing + Excel normalization
# ---------------------------------------------------------------------------


def parse_year_month_alias(path: Path) -> Tuple[int, int, str]:
    """
    Extract year, month, alias from filename like '2026_03_devon.xlsx'.

    Returns:
        (year, month, alias_lower)
    """
    name = path.stem  # e.g. "2026_03_devon"
    parts = name.split("_")
    if len(parts) < 3:
        raise ValueError(f"Filename {path.name!r} does not match 'YYYY_MM_alias.xlsx' pattern")

    year_str, month_str, alias = parts[0], parts[1], "_".join(parts[2:])
    year = int(year_str)
    month = int(month_str)
    return year, month, alias.lower()


def normalize_str(value: Any) -> str:
    """Convert Excel cell value to UPPERCASE string without leading/trailing spaces."""
    if value is None:
        return ""
    return str(value).strip().upper()


def to_int_day(value: Any) -> Optional[int]:
    """
    Convert Excel day from column A to an integer (1..31), or None if invalid.
    Handles int, float like 1.0, and string digits "1".
    """
    if value is None:
        return None

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return None

    if isinstance(value, str):
        s = value.strip()
        if s.isdigit():
            return int(s)

    return None


def is_preferred(value_norm: str) -> bool:
    """True for 'CHCĘ' / 'CHCE'."""
    return value_norm.startswith("CHC")


def is_unavailable(value_norm: str) -> bool:
    """True for 'NIE MOGĘ' / 'NIE MOGE'."""
    return value_norm.startswith("NIE MOG")


def load_day_lists_from_excel(
    path: Path,
) -> Tuple[List[int], List[int], List[int], List[int], Optional[str]]:
    """
    Read Excel file and return:
        preferred_onsite_days,
        unavailable_onsite_days,
        preferred_oncall_days,
        unavailable_oncall_days,
        comment

    Excel columns assumed:
    A: day number (1..31)
    C: onsite preference text (MOGĘ / NIE MOGĘ / CHCĘ)
    D: on-call preference text (MOGĘ / NIE MOGĘ / CHCĘ)
    """
    wb = load_workbook(path, data_only=True)
    ws = wb.active
    assert ws is not None, "Workbook has no active worksheet"

    preferred_onsite_days: List[int] = []
    unavailable_onsite_days: List[int] = []
    preferred_oncall_days: List[int] = []
    unavailable_oncall_days: List[int] = []
    comment: Optional[str] = None

    # 1) Read day rows
    for row_idx in range(2, ws.max_row + 1):
        day = to_int_day(ws[f"A{row_idx}"].value)
        if day is None:
            continue

        onsite_value = normalize_str(ws[f"C{row_idx}"].value)
        oncall_value = normalize_str(ws[f"D{row_idx}"].value)

        # Onsite
        if is_preferred(onsite_value):
            preferred_onsite_days.append(day)
        elif is_unavailable(onsite_value):
            unavailable_onsite_days.append(day)

        # On-call
        if is_preferred(oncall_value):
            preferred_oncall_days.append(day)
        elif is_unavailable(oncall_value):
            unavailable_oncall_days.append(day)

    # 2) Comment row from bottom
    for row_idx in range(ws.max_row, 1, -1):
        raw = ws[f"B{row_idx}"].value or ws[f"A{row_idx}"].value
        if raw is None:
            continue

        text = str(raw).strip()
        if not text:
            continue

        if not text.upper().startswith("KOMENTARZ"):
            continue

        # Remove "KOMENTARZ" and optional ":"
        rest = text[len("KOMENTARZ") :].lstrip()
        if rest.startswith(":"):
            rest = rest[1:].lstrip()

        comment = rest or None
        break

    # 3) Keep them clean (deduplicate + sort)
    preferred_onsite_days = sorted(set(preferred_onsite_days))
    unavailable_onsite_days = sorted(set(unavailable_onsite_days))
    preferred_oncall_days = sorted(set(preferred_oncall_days))
    unavailable_oncall_days = sorted(set(unavailable_oncall_days))

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
    """Resolve doctor_id from alias -> (first_name,last_name) -> Doctor row."""
    if alias not in ALIAS_TO_NAME:
        raise KeyError(f"Alias {alias!r} not found in ALIAS_TO_NAME mapping")

    first_name, last_name = ALIAS_TO_NAME[alias]

    stmt = select(Doctor).where(Doctor.first_name == first_name).where(Doctor.last_name == last_name)
    doctor = session.execute(stmt).scalar_one_or_none()

    if doctor is None:
        raise RuntimeError(f"Doctor not found in DB for alias {alias!r} -> ({first_name!r}, {last_name!r})")

    return int(doctor.id)


def get_or_create_working(session, doctor_id: int, year: int, month: int) -> PreferenceWorking:
    """Upsert working row (unique on doctor_id+year+month)."""
    stmt = (
        select(PreferenceWorking)
        .where(PreferenceWorking.doctor_id == doctor_id)
        .where(PreferenceWorking.year == year)
        .where(PreferenceWorking.month == month)
    )
    row = session.execute(stmt).scalar_one_or_none()

    if row is not None:
        return row

    row = PreferenceWorking(
        doctor_id=doctor_id,
        year=year,
        month=month,
        # lock_version default is handled by ORM/server_default
    )
    session.add(row)
    session.flush()
    return row


def get_or_create_pointer(session, doctor_id: int, year: int, month: int) -> PreferencePointer:
    """Upsert pointer row (unique on doctor_id+year+month)."""
    stmt = (
        select(PreferencePointer)
        .where(PreferencePointer.doctor_id == doctor_id)
        .where(PreferencePointer.year == year)
        .where(PreferencePointer.month == month)
    )
    row = session.execute(stmt).scalar_one_or_none()

    if row is not None:
        return row

    row = PreferencePointer(
        doctor_id=doctor_id,
        year=year,
        month=month,
    )
    session.add(row)
    session.flush()
    return row


def editable_payload_from_working(row: PreferenceWorking) -> dict:
    """
    IMPORTANT: match the service's _editable_payload_from_working().
    This ensures your system can use the seeded versions like normal UI checkpoints.
    """
    return {
        "unavailable_onsite_days": row.unavailable_onsite_days or [],
        "unavailable_oncall_days": row.unavailable_oncall_days or [],
        "preferred_onsite_days": row.preferred_onsite_days or [],
        "preferred_oncall_days": row.preferred_oncall_days or [],
        "min_onsite_total": row.min_onsite_total,
        "max_onsite_total": row.max_onsite_total,
        "target_onsite_total": row.target_onsite_total,
        "min_oncall_total": row.min_oncall_total,
        "max_oncall_total": row.max_oncall_total,
        "target_oncall_total": row.target_oncall_total,
        "max_onsite_weekends": row.max_onsite_weekends,
        "target_onsite_weekends": row.target_onsite_weekends,
        "max_oncall_weekends": row.max_oncall_weekends,
        "target_oncall_weekends": row.target_oncall_weekends,
        "preferred_onsite_weekdays": row.preferred_onsite_weekdays or [],
        "preferred_oncall_weekdays": row.preferred_oncall_weekdays or [],
        "avoid_onsite_weekdays": row.avoid_onsite_weekdays or [],
        "avoid_oncall_weekdays": row.avoid_oncall_weekdays or [],
        "allow_weekend_consecutive_onsite_oncall": row.allow_weekend_consecutive_onsite_oncall,
        "preferred_partners": row.preferred_partners or [],
        "comments": row.comments,
    }


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------


def process_single_file(session, path: Path) -> None:
    """Import one Excel file into March 2026 tables."""
    year, month, alias = parse_year_month_alias(path)

    # Safety: only import March 2026
    if year != TARGET_YEAR or month != TARGET_MONTH:
        print(f"[SKIP] {path.name} -> year={year}, month={month} (target 2026-03)")
        return

    doctor_id = get_doctor_id_by_alias(session, alias)

    (
        preferred_onsite_days,
        unavailable_onsite_days,
        preferred_oncall_days,
        unavailable_oncall_days,
        comment,
    ) = load_day_lists_from_excel(path)

    print(f"[FILE] {path.name} -> doctor_id={doctor_id}, alias={alias}, year={year}, month={month}")

    # 1) Upsert working and overwrite editable fields
    working = get_or_create_working(session, doctor_id, year, month)

    working.preferred_onsite_days = preferred_onsite_days
    working.unavailable_onsite_days = unavailable_onsite_days
    working.preferred_oncall_days = preferred_oncall_days
    working.unavailable_oncall_days = unavailable_oncall_days
    working.comments = comment

    # Optional: keep other fields as-is (totals/weekdays/partners etc.).
    # If Excel does not contain them, we do NOT touch them here.

    now = datetime.utcnow()
    working.last_saved_at = now
    working.last_saved_by_user_id = ADMIN_USER_ID
    working.last_saved_by_role = ADMIN_ROLE
    working.lock_version = (working.lock_version or 0) + 1  # mimic "some write happened"

    # 2) Create a new checkpoint version from working (append-only)
    payload = editable_payload_from_working(working)

    version = PreferenceVersion(
        doctor_id=doctor_id,
        year=year,
        month=month,
        kind="checkpoint",
        payload=payload,
        created_at=now,
        created_by_user_id=ADMIN_USER_ID,
        created_by_role=ADMIN_ROLE,
        note="Seeded from Excel file (2026_03 import)",
    )
    session.add(version)
    session.flush()  # version.id available

    # 3) Upsert pointer and point it to the new version (mark as submitted)
    pointer = get_or_create_pointer(session, doctor_id, year, month)
    pointer.current_version_id = int(version.id)
    pointer.submitted_at = now
    pointer.submitted_by_user_id = ADMIN_USER_ID
    pointer.submitted_by_role = ADMIN_ROLE

    print(f"  -> created version id={version.id} and updated pointer")


def main() -> None:
    """Entry point: import all xlsx files from EXCEL_DIR."""
    if not EXCEL_DIR.exists():
        raise RuntimeError(f"Directory {EXCEL_DIR!r} does not exist")

    excel_files = sorted(EXCEL_DIR.glob("*.xlsx"))
    if not excel_files:
        print(f"No .xlsx files found in {EXCEL_DIR}")
        return

    session = SessionLocal()
    try:
        for path in excel_files:
            process_single_file(session, path)

        session.commit()
        print("Done. All matching files processed and committed.")
    except Exception as exc:
        session.rollback()
        print(f"ERROR: {exc}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
