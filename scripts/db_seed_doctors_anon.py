# backend/scripts/db_seed_doctors_anon.py
"""
Seed script: create anonymous doctors from CSV + login users.

Usage (from repo root):

    python -m backend.scripts.db_seed_doctors_anon

What this script does NOW:
- Reads data from backend/data/seeds/doctors_anon.csv
- For each row:
  - creates or updates a Doctor row (based on unique email)
  - creates or updates a linked User row (role=doctor)
    * login:   doctor's email from CSV
    * password: "<alias>123"  (alias from CSV, lowercased)
- Additionally ensures a demo admin user exists:
    * admin@hospital.org / admin123 (role=admin)

Idempotent-ish:
- Running multiple times will NOT create duplicate Doctors / Users.
- Existing rows are updated to match CSV.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.session import SessionLocal
from backend.models.common_enums import DoctorRole, UserRole
from backend.models.orm.doctor import Doctor
from backend.models.orm.user import User
from backend.utils.security import hash_password

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


def upsert_user_for_doctor(
    session: Session,
    *,
    doctor: Doctor,
    alias: Optional[str],
) -> None:
    """
    Ensure there is a User linked 1:1 to given Doctor.

    - Login: doctor's email (must be non-empty).
    - Password: "<alias>123" (alias lowercased); if alias is missing,
      we skip user creation.
    - Role: UserRole.doctor.
    - is_active: copied from Doctor.is_active.
    """
    if not doctor.email:
        # No email -> we cannot create a login for this doctor.
        # This is a hard requirement in our auth model.
        print(
            f"[WARN] Doctor #{doctor.id} {doctor.first_name} {doctor.last_name} "
            f"has no email, skipping User creation."
        )
        return

    alias = (alias or "").strip()
    if not alias:
        # Alias is missing -> we cannot build password as "<alias>123".
        print(
            f"[WARN] Doctor #{doctor.id} {doctor.first_name} {doctor.last_name} "
            f"has empty alias, skipping User creation."
        )
        return

    password_plain = f"{alias.lower()}123"

    # Find existing user by email (email is unique in users table).
    user: User | None = session.execute(select(User).where(User.email == doctor.email)).scalars().one_or_none()

    if user is None:
        # Create new user for this doctor.
        user = User(
            email=doctor.email,
            role=UserRole.doctor,
            password_hash=hash_password(password_plain),
            is_active=doctor.is_active,
            doctor_id=doctor.id,
        )
        session.add(user)
        session.flush()
        print(
            f"[INFO] Created User for doctor #{doctor.id} ({doctor.email}), "
            f"password='{password_plain}' (plain, before hashing)."
        )
    else:
        # Update existing user to keep 1:1 link and activity in sync.
        changed = False

        if user.doctor_id != doctor.id:
            user.doctor_id = doctor.id
            changed = True

        if user.role != UserRole.doctor:
            user.role = UserRole.doctor
            changed = True

        # Keep user.is_active in sync with doctor.
        if user.is_active != doctor.is_active:
            user.is_active = doctor.is_active
            changed = True

        if changed:
            print(
                f"[INFO] Updated existing User for doctor #{doctor.id} "
                f"({doctor.email}) to keep 1:1 link and flags in sync."
            )


def ensure_admin_user(session: Session) -> None:
    """
    Ensure there is an admin user for manual testing.

    Credentials:
        email:    admin@hospital.org
        password: admin123

    Role: UserRole.admin
    """
    email = "admin@hospital.org"
    user: User | None = session.execute(select(User).where(User.email == email)).scalars().one_or_none()

    if user is None:
        user = User(
            email=email,
            role=UserRole.admin,
            password_hash=hash_password("admin123"),
            is_active=True,
            doctor_id=None,
        )
        session.add(user)
        session.flush()
        print("[INFO] Created admin user: admin@hospital.org / admin123")
    else:
        # Make sure this user really is an admin and active.
        changed = False
        if user.role != UserRole.admin:
            user.role = UserRole.admin
            changed = True
        if not user.is_active:
            user.is_active = True
            changed = True
        if changed:
            print("[INFO] Updated existing admin user to role=admin, is_active=True")


def upsert_doctor(session: Session, row: Dict[str, Any]) -> None:
    """
    Ensure that a Doctor exists (create or update) based on email.

    Strategy:
    - use email as unique key (it is unique in DB),
    - if doctor with this email exists: update fields,
    - otherwise: create new doctor,
    - then ensure a linked User exists (login + password) based on alias.
    """

    # --- 1. Extract and normalize CSV fields ---

    alias = row.get("alias", "").strip()
    first_name = row["first_name"].strip()
    last_name = row["last_name"].strip()
    role_str = row["role"].strip().lower()  # "specialist" | "resident"
    email = row["email"].strip()

    # Optional flags
    is_head = parse_bool(row.get("is_head", ""))
    is_active = parse_bool(row.get("is_active", "true"))

    # Convert string role to DoctorRole enum.
    try:
        doctor_role = DoctorRole(role_str)
    except ValueError as exc:
        raise ValueError(f"Unknown doctor role in CSV: {role_str!r}") from exc

    # --- 2. Find existing doctor by email (unique key) ---

    doctor: Doctor | None = session.execute(select(Doctor).where(Doctor.email == email)).scalars().one_or_none()

    if doctor is None:
        # Doctor does not exist yet → create new one.
        doctor = Doctor(
            first_name=first_name,
            last_name=last_name,
            role=doctor_role,
            is_active=is_active,
            is_head=is_head,
            email=email,
        )
        session.add(doctor)
        session.flush()  # assign doctor.id
        print(
            f"[INFO] Created Doctor #{doctor.id}: {doctor.first_name} {doctor.last_name} "
            f"({doctor.role.value}) email={doctor.email} alias={alias!r}"
        )
    else:
        # Doctor exists → update its fields to match CSV.
        doctor.first_name = first_name
        doctor.last_name = last_name
        doctor.role = doctor_role
        doctor.is_head = is_head
        doctor.is_active = is_active
        # email stays the same (we matched by email already)

        print(
            f"[INFO] Updated Doctor #{doctor.id}: {doctor.first_name} {doctor.last_name} "
            f"({doctor.role.value}) email={doctor.email} alias={alias!r}"
        )

    # --- 3. Ensure corresponding User for this doctor (login + password) ---

    upsert_user_for_doctor(session, doctor=doctor, alias=alias)


def main() -> None:
    """
    Main entry point for the seed script.

    - Opens DB session.
    - Ensures admin user exists.
    - Reads CSV file.
    - Upserts doctors and their login Users.
    """

    if not DATA_PATH.exists():
        raise FileNotFoundError(f"CSV file not found: {DATA_PATH}")

    with SessionLocal() as session:
        # First ensure demo admin user.
        ensure_admin_user(session)

        # Then process all doctors from CSV.
        with DATA_PATH.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                upsert_doctor(session, row)

        # Commit all changes (INSERTs/UPDATEs) in one transaction.
        session.commit()
        print("\n[OK] Doctors + Users seed committed.\n")


if __name__ == "__main__":
    main()
