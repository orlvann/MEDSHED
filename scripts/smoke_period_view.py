"""
Smoke Test: SchedulingService.get_period_view(year, month)

What this script verifies
-------------------------
A) Skeleton view (no data at all):
   - working.exists == False
   - draft is empty (no version_id)
   - published is empty (no version_id)
   - diagnostics is None

B) Working only (no pointers):
   - After save_working(...) WITHOUT any prior generate/checkpoint/publish
   - working.exists == True
   - draft is empty, published is empty
   - diagnostics is None

C) Working + Draft pointer (+diagnostics):
   - After checkpoint(...)
   - draft.version_id is not None
   - diagnostics is present (tied to the draft version)
   - published remains empty

How it works
------------
1) Wipes the target period {year, month} from schedules tables (versions/pointers/working).
2) Calls svc.get_period_view(...) and asserts shape for scenario A.
3) Creates ONLY a working snapshot via svc.save_working(...) and asserts scenario B.
4) Calls svc.checkpoint(...) to create a draft version & pointer and asserts scenario C.

How to run
----------
python -m scripts.smoke_period_view

WARNING
-------
This script deletes schedule data for the chosen {year, month}. Adjust constants if needed.
"""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import delete, select

from backend.db.session import SessionLocal
from backend.models.orm.schedule import SchedulePointer, ScheduleVersion, ScheduleWorking
from backend.models.schemas.schedule import Assignment
from backend.services.scheduling_service import SchedulingService


def _wipe_period(year: int, month: int) -> None:
    """Idempotently remove all schedule records for the given {year, month}."""
    with SessionLocal() as s:
        ids = s.scalars(
            select(ScheduleVersion.id).where(
                ScheduleVersion.year == year,
                ScheduleVersion.month == month,
            )
        ).all()
        if ids:
            s.execute(delete(ScheduleVersion).where(ScheduleVersion.id.in_(ids)))
        s.execute(delete(ScheduleWorking).where(ScheduleWorking.year == year, ScheduleWorking.month == month))
        s.execute(delete(SchedulePointer).where(SchedulePointer.year == year, SchedulePointer.month == month))
        s.commit()


def main() -> None:
    svc = SchedulingService()

    # Adjust if needed; the script wipes this period.
    year, month = 2025, 12
    print(f"0) WIPE state for period {year}-{month:02d}")
    _wipe_period(year, month)

    # ----------------------- A) SKELETON (no data at all) -----------------------
    print("\nA) PERIOD VIEW — Skeleton (no working, no pointers)")
    pv = svc.get_period_view(year, month)
    assert pv.year == year and pv.month == month
    assert pv.working.exists is False, "Expected working.exists == False in skeleton"
    assert pv.draft.version_id is None, "Expected empty draft (no version_id)"
    assert pv.published.version_id is None, "Expected empty published (no version_id)"
    assert pv.diagnostics is None, "Expected diagnostics == None when no draft pointer"
    print("   -> skeleton OK ✅")

    # ----------------------- B) WORKING ONLY (no pointers) ----------------------
    print("\nB) CREATE ONLY WORKING via save_working(...) (no pointers)")
    messy_assignments: List[Dict[str, Any]] = [
        {"day": 2, "shift_type": "on_call", "doctor_id": 3},
        {"day": 1, "shift_type": "on_duty", "doctor_id": 1},
        {"day": 1, "shift_type": "on_duty", "doctor_id": 1},  # duplicate to check normalization
    ]
    ack = svc.save_working(
        year,
        month,
        assignments=[Assignment(**a) for a in messy_assignments],
        meta={"labels": ["z", "a", "a"]},
        if_match_lock_version=None,  # first write (row may be created)
        updated_by_user_id=1001,
    )
    print(f"   -> working saved; lock_version now {ack.lock_version}")

    pv = svc.get_period_view(year, month)
    assert pv.working.exists is True, "Expected working.exists == True after save_working"
    assert pv.draft.version_id is None, "Draft should be empty (no checkpoint yet)"
    assert pv.published.version_id is None, "Published should be empty"
    assert pv.diagnostics is None, "Diagnostics should be None without draft pointer"
    # working normalization quick check
    assert pv.working.meta.get("labels") == ["a", "z"], "Working labels should be normalized to ['a','z']"
    print("   -> working-only view OK ✅")

    # ---------------- C) WORKING + DRAFT POINTER (+diagnostics) -----------------
    print("\nC) CHECKPOINT — create draft pointer & diagnostics")
    cp = svc.checkpoint(year, month, note=None, user_id=1001)
    assert cp.draft.version_id is not None, "Checkpoint must return a draft version_id"
    print(f"   -> draft created: version_id={cp.draft.version_id}")

    pv = svc.get_period_view(year, month)
    assert pv.working.exists is True, "Working should still exist"
    assert pv.draft.version_id is not None, "Draft should be present after checkpoint"
    assert pv.diagnostics is not None, "Diagnostics should be present for draft pointer"
    assert pv.published.version_id is None, "Published should still be empty at this stage"
    print("   -> draft+diagnostics view OK ✅")

    print("\nSMOKE OK ✅  get_period_view covers: skeleton, working-only, working+draft(+diagnostics).")


if __name__ == "__main__":
    main()
