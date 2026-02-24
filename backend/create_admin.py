"""
Create an admin user in the database.

Usage (local):
    PYTHONPATH=. python -m backend.create_admin --email admin@example.com --password secret123

Usage (Docker):
    docker compose exec backend python -m backend.create_admin --email admin@example.com --password secret123
"""

import argparse
import sys

from sqlalchemy import select

from backend.db.session import SessionLocal
from backend.models.common_enums import UserRole
from backend.models.orm.user import User
from backend.utils.security import hash_password


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an admin user")
    parser.add_argument("--email", required=True, help="Admin email address")
    parser.add_argument("--password", required=True, help="Admin password")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        existing = db.execute(select(User).where(User.email == args.email)).scalar_one_or_none()
        if existing:
            print(f"User with email {args.email} already exists (id={existing.id}, role={existing.role.value})")
            sys.exit(0)

        user = User(
            email=args.email,
            role=UserRole.admin,
            password_hash=hash_password(args.password),
            is_active=True,
            doctor_id=None,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        print(f"Admin created: id={user.id}, email={user.email}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
