"""
Show current rows from Doctors, Users, and Preferences tables.
For local dev only.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.session import SessionLocal
from backend.models.orm.doctor import Doctor
from backend.models.orm.preference import (
    PreferenceDeadline,  # <- singular
    PreferencePointer,
    PreferenceVersion,
    PreferenceWorking,
)
from backend.models.orm.user import User


def print_doctors(db: Session) -> None:
    print("== Doctors ==")
    for d in db.execute(select(Doctor).order_by(Doctor.id)).scalars():
        print(f"#{d.id} {d.first_name} {d.last_name} " f"role={d.role.value} email={d.email}")


def print_users(db: Session) -> None:
    print("\n== Users ==")
    for u in db.execute(select(User).order_by(User.id)).scalars():
        print(f"#{u.id} {u.email} role={u.role.value} " f"active={u.is_active} doctor_id={u.doctor_id}")

    print("\n== Users joined with Doctors (if linked) ==")
    stmt = select(User, Doctor).join(Doctor, Doctor.id == User.doctor_id, isouter=True).order_by(User.id)
    for u, d in db.execute(stmt).all():
        doc_label = f"{d.first_name} {d.last_name}" if d else "—"
        print(f"user #{u.id} {u.email} -> doctor: {doc_label}")


def print_preferences_deadlines(db: Session) -> None:
    print("\n== Preferences: Deadlines ==")
    for row in db.execute(
        select(PreferenceDeadline).order_by(PreferenceDeadline.year, PreferenceDeadline.month)
    ).scalars():
        print(f"{row.year:04d}-{row.month:02d} " f"deadline_utc={row.deadline_utc} org_tz={row.org_timezone}")


def print_preferences_working(db: Session) -> None:
    print("\n== Preferences: Working ==")
    for row in db.execute(
        select(PreferenceWorking).order_by(
            PreferenceWorking.doctor_id,
            PreferenceWorking.year,
            PreferenceWorking.month,
        )
    ).scalars():
        print(
            f"doc#{row.doctor_id} {row.year:04d}-{row.month:02d} "
            f"lock_version={row.lock_version} "
            f"preferred_duty_days={getattr(row, 'preferred_duty_days', None)}"
        )


def print_preferences_pointers(db: Session) -> None:
    print("\n== Preferences: Pointers ==")
    for row in db.execute(
        select(PreferencePointer).order_by(
            PreferencePointer.doctor_id,
            PreferencePointer.year,
            PreferencePointer.month,
        )
    ).scalars():
        print(
            f"doc#{row.doctor_id} {row.year:04d}-{row.month:02d} "
            f"current_checkpoint_id={row.current_checkpoint_id} "
            f"submitted_at={row.submitted_at} by={row.submitted_by_role}"
        )


def print_preferences_versions(db: Session) -> None:
    print("\n== Preferences: Versions ==")
    for row in db.execute(select(PreferenceVersion).order_by(PreferenceVersion.created_at)).scalars():
        print(
            f"{row.version_id} -> doc#{row.doctor_id} "
            f"{row.year:04d}-{row.month:02d} created_at={row.created_at} "
            f"by={row.created_by_role}"
        )


def main() -> None:
    db: Session = SessionLocal()
    try:
        print_doctors(db)
        print_users(db)
        print_preferences_deadlines(db)
        print_preferences_working(db)
        print_preferences_pointers(db)
        print_preferences_versions(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
