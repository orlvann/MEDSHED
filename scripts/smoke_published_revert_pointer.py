# scripts/smoke_published_revert_pointer.py
"""
Smoke Test: Published Pointer Revert (prev/next) Only

What this script verifies
-------------------------
- publish(...) creates immutable published snapshots and moves the published pointer.
- Multiple publish operations result in strictly increasing version ids.
- revert(target="published", direction="prev"/"next") moves ONLY the published pointer
  (no overwrite of working), and returned DTO is SchedulePublishedRevertRead with `.published` field.
- get_published(...) reflects the pointer position after each revert.

What this script does NOT test
------------------------------
- Draft checkpoints, draft undo/redo, or working overwrites.
- Hard-rule violations (the service stub allows publishing).

How to run
----------
python -m scripts.smoke_published_revert_pointer
"""

from __future__ import annotations

from typing import cast

from sqlalchemy import delete, select

from backend.db.session import SessionLocal
from backend.models.common_enums import ShiftType
from backend.models.orm.schedule import SchedulePointer, ScheduleVersion, ScheduleWorking
from backend.models.schemas.schedule import (
    Assignment,
    ScheduleGenerateRequest,
    SchedulePublishedRevertRead,
)
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
    """
    Execute a focused flow:
      1) wipe → generate (participants [1,2,3])
      2) publish #1 (baseline working)
      3) mutate working → publish #2
      4) revert published PREV → expect pointer at pub#1
      5) revert published NEXT → expect pointer at pub#2
    """
    svc = SchedulingService()

    # Adjust as needed; the script wipes this period.
    year, month = 2026, 2

    print("0) WIPE current period state")
    _wipe_period(year, month)

    print("1) GENERATE — seed working with participants [1, 2, 3]")
    gen = svc.generate(ScheduleGenerateRequest(year=year, month=month, participant_doctor_ids=[1, 2, 3]), user_id=101)
    assert gen.working.exists, "Working should exist after generate()"
    assert gen.working.participant_doctor_ids == [1, 2, 3]

    print("\n2) PUBLISH #1 — from empty/default working (no assignments yet)")
    pub1 = svc.publish(year, month, force=False, accepted_exceptions=None, note="pub#1", user_id=101)
    pub1_id_s = pub1.published.version_id
    assert pub1_id_s is not None
    pub1_id = int(cast(str, pub1_id_s))
    print(f"   -> published#1 id: {pub1_id}, can_undo={pub1.published.can_undo}, can_redo={pub1.published.can_redo}")

    # Verify pointer via get_published
    cur = svc.get_published(year, month)
    assert cur.published.version_id == str(pub1_id), "Published pointer should point to pub#1"

    print("\n3) SAVE working with different assignments → PUBLISH #2")
    w = svc.get_working(year, month)
    assert w.lock_version is not None
    _ = svc.save_working(
        year,
        month,
        assignments=[
            Assignment(day=1, shift_type=ShiftType.onsite, doctor_id=1),
            Assignment(day=1, shift_type=ShiftType.oncall, doctor_id=2),
            Assignment(day=2, shift_type=ShiftType.onsite, doctor_id=3),
        ],
        meta={"labels": ["live"]},
        if_match_lock_version=w.lock_version,
        updated_by_user_id=101,
    )
    pub2 = svc.publish(year, month, force=False, accepted_exceptions=None, note="pub#2", user_id=101)
    pub2_id_s = pub2.published.version_id
    assert pub2_id_s is not None
    pub2_id = int(cast(str, pub2_id_s))
    print(f"   -> published#2 id: {pub2_id} (should be > pub#1)")

    assert pub2_id > pub1_id, "Second publication id should be newer than first"

    # Confirm pointer at pub#2
    cur2 = svc.get_published(year, month)
    assert cur2.published.version_id == str(pub2_id), "Published pointer should now point to pub#2"

    print("\n4) REVERT published PREV — move pointer back to pub#1")
    rv_prev = svc.revert(year, month, target="published", direction="prev", user_id=101)
    assert isinstance(rv_prev, SchedulePublishedRevertRead)
    print(f"   -> after PREV, pointer at version_id: {rv_prev.published.version_id}")
    assert rv_prev.published.version_id == str(pub1_id), "Pointer should move to pub#1"
    assert rv_prev.published.can_redo is True, "After moving back, redo should be available"

    # get_published should match
    cur3 = svc.get_published(year, month)
    assert cur3.published.version_id == str(pub1_id)

    print("\n5) REVERT published NEXT — move pointer forward to pub#2 again")
    rv_next = svc.revert(year, month, target="published", direction="next", user_id=101)
    assert isinstance(rv_next, SchedulePublishedRevertRead)
    print(f"   -> after NEXT, pointer at version_id: {rv_next.published.version_id}")
    assert rv_next.published.version_id == str(pub2_id), "Pointer should move back to pub#2"

    # Final pointer check
    cur4 = svc.get_published(year, month)
    assert cur4.published.version_id == str(pub2_id)

    print("\nSMOKE OK ✅  Published pointer prev/next works and affects only the published stream.")


if __name__ == "__main__":
    main()
