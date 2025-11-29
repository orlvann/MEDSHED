"""
Seed script: create anonymous doctors from CSV.

Usage (from repo root):

    python -m scripts.db_seed_doctors_anon

What this script does NOW:
- Reads data from data/seeds/doctors_anon.csv
- For each row:
  - creates or updates a Doctor row (no Users, no passwords yet)

IMPORTANT:
- This script does NOT touch users or passwords.
- Security / auth team can later extend it to also create User rows.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.session import SessionLocal
from backend.models.common_enums import DoctorRole
from backend.models.orm.doctor import Doctor

# Path to the CSV with doctors data.
DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "seeds" / "doctors_anon.csv"


def parse_bool(value: str) -> bool:
    """
    Convert string from CSV to bool.

    Accepts: "true"/"false", "t"/"f", "1"/"0", "yes"/"no" (case-insensitive).
    Anything else is treated as False.
    """
    if value is None:
        return False
    value_norm = value.strip().lower()
    return value_norm in {"true", "t", "1", "yes", "y"}


def upsert_doctor(session: Session, row: Dict[str, Any]) -> None:
    """
    Ensure that a Doctor exists (create or update) based on email.

    Strategy:
    - use email as unique key (it is unique in DB),
    - if doctor with this email exists: update fields,
    - otherwise: create new doctor.
    """

    # --- 1. Extract and normalize CSV fields ---

    # Required fields (as we designed in doctors_anon.csv)
    first_name = row["first_name"].strip()
    last_name = row["last_name"].strip()
    role_str = row["role"].strip().lower()  # "specialist" | "resident"
    email = row["email"].strip()

    # Optional column: is_head (can be "true"/"false", "1"/"0", etc.)
    is_head = parse_bool(row.get("is_head", ""))

    # There might also be an "alias" column in CSV, but we ignore it here.
    # alias = row.get("alias", "").strip()

    # Convert string role to DoctorRole enum.
    try:
        doctor_role = DoctorRole(role_str)
    except ValueError as exc:
        raise ValueError(f"Unknown doctor role in CSV: {role_str!r}") from exc

    # --- 2. Find existing doctor by email (unique key) ---

    doctor = session.execute(select(Doctor).where(Doctor.email == email)).scalar_one_or_none()

    if doctor is None:
        # Doctor does not exist yet → create new one.
        doctor = Doctor(
            first_name=first_name,
            last_name=last_name,
            role=doctor_role,
            is_active=True,
            is_head=is_head,
            email=email,
        )
        session.add(doctor)
    else:
        # Doctor exists → update its fields to match CSV.
        doctor.first_name = first_name
        doctor.last_name = last_name
        doctor.role = doctor_role
        doctor.is_head = is_head
        # email stays the same (we matched by email already, but we could also reassign)


def main() -> None:
    """
    Main entry point for the seed script.

    - Opens DB session.
    - Reads CSV file.
    - Upserts doctors.
    """

    if not DATA_PATH.exists():
        raise FileNotFoundError(f"CSV file not found: {DATA_PATH}")

    with SessionLocal() as session:
        with DATA_PATH.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                upsert_doctor(session, row)

        # Commit all changes (INSERTs/UPDATEs) in one transaction.
        session.commit()


if __name__ == "__main__":
    main()
