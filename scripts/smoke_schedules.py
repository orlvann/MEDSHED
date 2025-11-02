# scripts/smoke_schedules.py

from sqlalchemy.orm import Session

from backend.db.session import SessionLocal
from backend.models.orm.doctor import Doctor  # noqa: F401
from backend.models.orm.schedule import SchedulePointer, ScheduleVersion, ScheduleWorking

# --- te importy REJESTRUJĄ tabele w Base.metadata ---
from backend.models.orm.user import User  # noqa: F401


def run() -> None:
    db: Session = SessionLocal()
    try:
        # Working snapshot: upsert by PK (year, month)
        db.merge(
            ScheduleWorking(
                year=2026,
                month=2,
                payload={"assignments": [], "meta": {"note": "WIP"}},
                lock_version=0,
            )
        )

        # Draft version: immutable append
        v = ScheduleVersion(
            year=2026,
            month=2,
            payload={"assignments": [], "meta": {"cp": 1}},
            kind="draft",
        )
        db.add(v)
        db.flush()  # assigns v.id

        # Pointer to the new draft
        db.merge(
            SchedulePointer(
                year=2026,
                month=2,
                current_draft_version_id=v.id,
            )
        )

        db.commit()
        print("OK — working + draft + pointer inserted")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
