"""
Show current rows from Doctors and Users (with optional user->doctor join).
For local dev only.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.session import SessionLocal
from backend.models.ORM.doctor import Doctor
from backend.models.ORM.user import User


def main() -> None:
    db: Session = SessionLocal()
    try:
        print("== Doctors ==")
        for d in db.execute(select(Doctor).order_by(Doctor.id)).scalars():
            print(f"#{d.id} {d.first_name} {d.last_name} role={d.role.value} email={d.email}")

        print("\n== Users ==")
        for u in db.execute(select(User).order_by(User.id)).scalars():
            print(f"#{u.id} {u.email} role={u.role.value} active={u.is_active} " f"doctor_id={u.doctor_id}")

        print("\n== Users joined with Doctors (if linked) ==")
        stmt = select(User, Doctor).join(Doctor, Doctor.id == User.doctor_id, isouter=True).order_by(User.id)
        for u, d in db.execute(stmt).all():
            doc_label = f"{d.first_name} {d.last_name}" if d else "—"
            print(f"user #{u.id} {u.email} -> doctor: {doc_label}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
