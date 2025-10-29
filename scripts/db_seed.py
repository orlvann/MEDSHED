"""
Dev seed: create sample Doctors and Users for manual testing.

What it does:
- Inserts two Doctors (Anna Kowalska / Piotr Nowak) if they don't exist.
- Inserts two Users:
    * admin:    admin@hospital.org / admin123!
    * doctor:   anna@hospital.org  / doctor123!  (linked 1:1 to Doctor(Anna))
- Idempotent: running multiple times won't duplicate rows.

NOTE: Password hashing here is DEV-ONLY (sha256). For prod use passlib[bcrypt].
"""

from __future__ import annotations

import hashlib
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.session import SessionLocal
from backend.models.common_enums import DoctorRole, Role
from backend.models.orm.doctor import Doctor

# Preferences models are imported for completeness (not used for seeding now)
from backend.models.orm.preference import (  # noqa: F401
    PreferenceDeadline,  # <- singular
    PreferencePointer,
    PreferenceVersion,
    PreferenceWorking,
)
from backend.models.orm.user import User


# --- tiny DEV hash helper (DO NOT use in production) ---
def dev_hash_password(raw: str) -> str:
    return hashlib.sha256(("dev_salt::" + raw).encode("utf-8")).hexdigest()


def get_or_create_doctor(
    db: Session,
    *,
    first_name: str,
    last_name: str,
    role: DoctorRole,
    email: Optional[str] = None,
) -> Doctor:
    """Find by email (if provided), otherwise by (first_name, last_name, role)."""
    if email:
        doc = db.execute(select(Doctor).where(Doctor.email == email)).scalar_one_or_none()
        if doc:
            return doc

    # Fallback by (first_name, last_name, role) for NULL-email doctors
    doc = db.execute(
        select(Doctor).where(
            Doctor.first_name == first_name,
            Doctor.last_name == last_name,
            Doctor.role == role,
        )
    ).scalar_one_or_none()
    if doc:
        return doc

    doc = Doctor(first_name=first_name, last_name=last_name, role=role, email=email)
    db.add(doc)
    db.flush()  # populate doc.id
    return doc


def get_or_create_user(
    db: Session,
    *,
    email: str,
    role: Role,
    password_plain: str,
    doctor_id: Optional[int] = None,
) -> User:
    """Find by email; if not found, create. Keep 1:1 doctor link if provided."""
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user:
        if doctor_id and user.doctor_id != doctor_id:
            user.doctor_id = doctor_id
        return user

    user = User(
        email=email,
        role=role,
        password_hash=dev_hash_password(password_plain),
        is_active=True,
        doctor_id=doctor_id,
    )
    db.add(user)
    db.flush()
    return user


def main() -> None:
    db: Session = SessionLocal()
    try:
        # 1) Doctors
        anna = get_or_create_doctor(
            db,
            first_name="Anna",
            last_name="Kowalska",
            role=DoctorRole.specialist,
            email="anna@example.com",
        )
        piotr = get_or_create_doctor(
            db,
            first_name="Piotr",
            last_name="Nowak",
            role=DoctorRole.resident,
            email=None,
        )

        # 2) Users (admin + doctor linked to Anna)
        admin_user = get_or_create_user(
            db,
            email="admin@hospital.org",
            role=Role.admin,
            password_plain="admin123!",
            doctor_id=None,
        )
        doctor_user = get_or_create_user(
            db,
            email="anna@hospital.org",
            role=Role.doctor,
            password_plain="doctor123!",
            doctor_id=anna.id,  # 1:1 link to Doctor(Anna)
        )

        db.commit()

        print("\n== Seed complete ==")
        print(f"Doctor: #{anna.id} {anna.first_name} {anna.last_name} " f"({anna.role.value}) email={anna.email}")
        print(f"Doctor: #{piotr.id} {piotr.first_name} {piotr.last_name} " f"({piotr.role.value}) email={piotr.email}")
        print(
            "User(admin):  {email} / admin123!  role={role} active={active}".format(
                email=admin_user.email,
                role=admin_user.role.value,
                active=admin_user.is_active,
            )
        )
        print(
            "User(doctor): {email} / doctor123! role={role} active={active} doctor_id={docid}".format(
                email=doctor_user.email,
                role=doctor_user.role.value,
                active=doctor_user.is_active,
                docid=doctor_user.doctor_id,
            )
        )
        print("\nLogin hint (DEV ONLY): passwords above; hashing is sha256 demo.")
        print("Wire AuthService to verify hashes and issue JWTs.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
