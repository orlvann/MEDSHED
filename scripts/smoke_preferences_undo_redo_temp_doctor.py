"""
Smoke test for preferences version navigation flags (can_undo / can_redo),
using a temporary Doctor record and full cleanup at the end.

What this script does:
1) Creates a temporary active doctor (best-effort, based on required columns).
2) Creates working row + 3 checkpoints for a given (year, month).
3) Moves pointer to first/middle/last checkpoint and calls get_working().
4) Prints can_undo/can_redo for each pointer position.
5) Deletes: PreferenceVersion, PreferencePointer, PreferenceWorking for that period + the temp doctor.

Notes:
- This will temporarily write to your DB but cleans up afterwards.
- Use on local/dev DB.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from typing import Any, cast

from sqlalchemy import Boolean, DateTime, Enum, Integer, String
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError

from backend.db.session import SessionLocal
from backend.models.orm.doctor import Doctor
from backend.models.orm.preference import PreferencePointer, PreferenceVersion, PreferenceWorking
from backend.services.preference_service import create_checkpoint, get_working


class FakeUserCtx:
    """
    Minimal actor object for preference_service.
    We avoid importing backend.routers.deps.UserCtx (it pulls auth/jose dependencies).

    Fields used by preference_service:
    - user_id
    - role
    - email (optional, only if your code expects it somewhere)
    """

    def __init__(self, *, user_id: int, role: str, email: str | None = None) -> None:
        self.user_id = user_id
        self.role = role
        self.email = email


def _utc_now() -> datetime:
    """Return timezone-aware UTC now."""
    return datetime.now(timezone.utc)


def _uniq_tag() -> str:
    """Small unique tag for temporary data."""
    return f"{int(_utc_now().timestamp())}_{os.getpid()}"


def _guess_value_for_column(col, *, tag: str):
    """
    Guess a sensible value for a required column.

    IMPORTANT:
    SQLAlchemy Enum can behave like a string type, so we must check Enum BEFORE String.
    """
    # Always try to make the temp doctor active if such column exists.
    if col.name == "is_active":
        return True

    col_type = col.type

    if isinstance(col_type, Boolean):
        return True

    if isinstance(col_type, Integer):
        # Use 0 as a safe default for required ints (except PK, which we skip).
        return 0

    if isinstance(col_type, DateTime):
        return _utc_now()

    if isinstance(col_type, Enum):
        # Pick first allowed enum value.
        enums = getattr(col_type, "enums", None)
        if enums:
            return enums[0]  # e.g. "specialist"
        return None

    if isinstance(col_type, String):
        # Unique-ish string per column to avoid collisions.
        return f"tmp_{tag}_{col.name}"

    # Unknown/complex types -> None (may fail if NOT NULL)
    return None


def _create_temp_doctor(session) -> int:
    """
    Create a temporary Doctor row.

    We inspect Doctor table columns and fill only required ones that don't have defaults.
    """
    tag = _uniq_tag()
    mapper = sa_inspect(Doctor)
    cols = list(mapper.columns)

    kwargs = {}
    for col in cols:
        # Skip primary key (usually autoincrement).
        if col.primary_key:
            continue

        # If nullable -> we can omit.
        if col.nullable:
            continue

        # If DB/ORM provides a default -> we can omit.
        if col.default is not None or col.server_default is not None:
            continue

        # If it is a required foreign key, guessing is risky.
        # We still try a guessed value, but this may fail with IntegrityError.
        kwargs[col.name] = _guess_value_for_column(col, tag=tag)

    # Ensure is_active is True if the column exists, even if it had a default.
    if "is_active" in [c.name for c in cols]:
        kwargs["is_active"] = True

    temp = Doctor(**kwargs)
    session.add(temp)
    session.flush()  # populate temp.id

    return int(temp.id)


def _cleanup_everything(session, *, doctor_id: int, year: int, month: int) -> None:
    """Delete preference rows for (doctor_id, year, month) and then the doctor."""
    # Delete preference data first (avoid FK constraint issues).
    session.query(PreferenceVersion).filter_by(year=year, month=month, doctor_id=doctor_id).delete()
    session.query(PreferencePointer).filter_by(year=year, month=month, doctor_id=doctor_id).delete()
    session.query(PreferenceWorking).filter_by(year=year, month=month, doctor_id=doctor_id).delete()

    # Delete the doctor.
    session.query(Doctor).filter_by(id=doctor_id).delete()

    session.commit()


def _set_working_comment(*, year: int, month: int, doctor_id: int, comment: str) -> None:
    """
    Upsert working row and set a unique comment so each checkpoint payload differs.
    """
    with SessionLocal() as session:
        row = session.query(PreferenceWorking).filter_by(year=year, month=month, doctor_id=doctor_id).one_or_none()
        if row is None:
            row = PreferenceWorking(year=year, month=month, doctor_id=doctor_id)
            session.add(row)
            session.flush()

        row.comments = comment

        # Minimal audit info
        row.last_saved_at = _utc_now()
        row.last_saved_by_user_id = 999
        row.last_saved_by_role = "admin"
        row.lock_version = (row.lock_version or 0) + 1

        session.commit()


def _get_versions(session, *, year: int, month: int, doctor_id: int) -> list[int]:
    """Return version IDs (ascending by id)."""
    versions = (
        session.query(PreferenceVersion)
        .filter_by(year=year, month=month, doctor_id=doctor_id)
        .order_by(PreferenceVersion.id.asc())
        .all()
    )
    return [int(v.id) for v in versions]


def _set_pointer(session, *, year: int, month: int, doctor_id: int, version_id: int) -> None:
    """Set pointer.current_version_id to selected version."""
    pointer = session.query(PreferencePointer).filter_by(year=year, month=month, doctor_id=doctor_id).one_or_none()
    if pointer is None:
        pointer = PreferencePointer(year=year, month=month, doctor_id=doctor_id)
        session.add(pointer)
        session.flush()

    pointer.current_version_id = int(version_id)
    pointer.submitted_at = _utc_now()
    pointer.submitted_by_user_id = 999
    pointer.submitted_by_role = "admin"
    session.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True)
    args = parser.parse_args()

    actor = FakeUserCtx(user_id=999, role="admin", email="temp-admin@example.local")
    doctor_id = None

    try:
        # 1) Create temp doctor
        with SessionLocal() as session:
            try:
                doctor_id = _create_temp_doctor(session)
                session.commit()
            except IntegrityError as e:
                session.rollback()
                raise SystemExit(
                    "FAILED to create temporary Doctor.\n"
                    "Most likely your Doctor table has required foreign keys (e.g. user_id NOT NULL)\n"
                    "or other required fields with constraints.\n"
                    "Paste:\n"
                    "- backend/models/orm/doctor.py\n"
                    "- the 'doctors' table columns from your Alembic init migration\n"
                    "- this traceback\n"
                    f"\nOriginal error: {e}\n"
                )

        print(f"Temporary doctor created: doctor_id={doctor_id} (year={args.year}, month={args.month})")

        # 2) Create 3 checkpoints
        for i in range(1, 4):
            _set_working_comment(year=args.year, month=args.month, doctor_id=doctor_id, comment=f"checkpoint v{i}")
            created = create_checkpoint(year=args.year, month=args.month, doctor_id=doctor_id, actor=cast(Any, actor))
            print(f"Created checkpoint version_id={created.version_id} (comments='{created.comments}')")

        # 3) Test flags for pointer at first/middle/last
        with SessionLocal() as session:
            version_ids = _get_versions(session, year=args.year, month=args.month, doctor_id=doctor_id)
            if len(version_ids) != 3:
                raise SystemExit(f"Expected 3 versions, got {len(version_ids)}: {version_ids}")

            v1, v2, v3 = version_ids
            print(f"Versions in DB: {version_ids}")

            _set_pointer(session, year=args.year, month=args.month, doctor_id=doctor_id, version_id=v2)
            dto = get_working(year=args.year, month=args.month, doctor_id=doctor_id, actor=cast(Any, actor))

            print(f"[Pointer=v2] can_undo={dto.can_undo} can_redo={dto.can_redo} (EXPECTED: True/True)")

            _set_pointer(session, year=args.year, month=args.month, doctor_id=doctor_id, version_id=v1)
            dto = get_working(year=args.year, month=args.month, doctor_id=doctor_id, actor=cast(Any, actor))

            print(f"[Pointer=v1] can_undo={dto.can_undo} can_redo={dto.can_redo} (EXPECTED: False/True)")

            _set_pointer(session, year=args.year, month=args.month, doctor_id=doctor_id, version_id=v3)
            dto = get_working(year=args.year, month=args.month, doctor_id=doctor_id, actor=cast(Any, actor))

            print(f"[Pointer=v3] can_undo={dto.can_undo} can_redo={dto.can_redo} (EXPECTED: True/False)")

    finally:
        # 4) Cleanup
        if doctor_id is not None:
            with SessionLocal() as session:
                _cleanup_everything(session, doctor_id=doctor_id, year=args.year, month=args.month)
            print("Cleanup done (temp doctor + preference rows removed).")


if __name__ == "__main__":
    main()
