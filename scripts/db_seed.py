"""
Insert a few sample records into the local SQLite DB for manual testing.
"""

from sqlalchemy.orm import Session

from backend.db.session import SessionLocal
from backend.models.common_enums import DoctorRole
from backend.models.ORM.doctor import Doctor


def main() -> None:
    db: Session = SessionLocal()
    try:
        doctors = [
            Doctor(first_name="Anna", last_name="Kowalska", role=DoctorRole.specialist, email="anna@example.com"),
            Doctor(first_name="Piotr", last_name="Nowak", role=DoctorRole.resident, email=None),
        ]
        db.add_all(doctors)
        db.commit()
        for d in doctors:
            db.refresh(d)
            print("Inserted:", d)
    finally:
        db.close()


if __name__ == "__main__":
    main()
