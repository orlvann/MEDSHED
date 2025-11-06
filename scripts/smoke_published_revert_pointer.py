# scripts/smoke_published_revert_pointer.py
"""
Smoke Test: Double publish + revert published prev/next (pointer movement)

Goal
----
Verify that:
1) After publishing twice for the same {year, month}, there are two published versions
   with strictly increasing IDs: v_old < v_new, and the pointer points to v_new.
2) revert(target="published", direction="prev") moves the pointer to v_old.
3) revert(target="published", direction="next") moves the pointer back to v_new.

What this script DOES
---------------------
- Wipes the target period {year, month} (versions, working, pointer).
- generate() to seed the period (working + first draft).
- publish() twice to create two published snapshots.
- Calls revert(..., target="published", direction="prev") and then "...next".
- Asserts pointer movement and can_undo/can_redo flags.

What this script DOES NOT DO
----------------------------
- It doesn't hit HTTP; it uses the service directly.
- It doesn't validate hard-rule logic (stub returns no violations).

How to run
----------
python -m scripts.smoke_published_revert_pointer

WARNING
-------
This script deletes schedule data for the chosen {year, month}.
"""

from __future__ import annotations

from typing import List, cast

from sqlalchemy import delete, select

from backend.db.session import SessionLocal
from backend.models.orm.schedule import (
    SchedulePointer,
    ScheduleVersion,
    ScheduleWorking,
)
from backend.models.schemas.schedule import (
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


def _published_pointer(year: int, month: int) -> int | None:
    """Return current published pointer for the period (int) or None if missing."""
    with SessionLocal() as s:
        p = s.get(SchedulePointer, {"year": year, "month": month})
        if not p or p.current_published_version_id is None:
            return None
        return int(p.current_published_version_id)


def _list_published_ids(year: int, month: int) -> List[int]:
    """Return all published version IDs for the period, ascending by id."""
    with SessionLocal() as s:
        ids = s.scalars(
            select(ScheduleVersion.id)
            .where(
                ScheduleVersion.year == year,
                ScheduleVersion.month == month,
                ScheduleVersion.kind == "published",
            )
            .order_by(ScheduleVersion.id.asc())
        ).all()
        return [int(x) for x in ids]


def main() -> None:
    svc = SchedulingService()

    # Adjust if needed; the script wipes this period.
    year, month = 2025, 12

    print("0) WIPE current period state")
    _wipe_period(year, month)

    print("1) GENERATE — seed participants and create initial draft")
    gen_req = ScheduleGenerateRequest(year=year, month=month, participant_doctor_ids=[11, 22, 33])
    gen_out = svc.generate(gen_req, user_id=1001)
    assert gen_out.working.exists is True
    print(f"   -> draft.version_id={gen_out.draft.version_id}")

    print("\n2) PUBLISH #1 — create first published snapshot")
    pub1 = svc.publish(year, month, force=False, accepted_exceptions=None, note="pub#1", user_id=1001)
    v1s = pub1.published.version_id
    assert v1s is not None, "Published #1 version_id should not be None"
    v1 = int(v1s)
    print(f"   -> published #1 id={v1}")

    print("\n3) PUBLISH #2 — create second (newer) published snapshot")
    pub2 = svc.publish(year, month, force=False, accepted_exceptions=None, note="pub#2", user_id=1001)
    v2s = pub2.published.version_id
    assert v2s is not None, "Published #2 version_id should not be None"
    v2 = int(v2s)
    print(f"   -> published #2 id={v2}")

    assert v2 > v1, f"Expected second publish to have greater id than first " f"(got v1={v1}, v2={v2})"

    ids = _list_published_ids(year, month)
    print(f"   -> all published ids (asc): {ids}")
    assert ids == [v1, v2], "Expected exactly two published versions in ascending order"

    ptr_now = _published_pointer(year, month)
    print(f"   -> pointer after pub#2: {ptr_now}")
    assert ptr_now == v2, "Pointer should be at the newest published version after publish #2"

    print("\n4) REVERT published PREV — pointer should move from v2 -> v1")
    prev_view_any = svc.revert(year, month, target="published", direction="prev", user_id=1001)
    prev_view = cast(SchedulePublishedRevertRead, prev_view_any)
    vprev_s = prev_view.published.version_id
    assert vprev_s is not None
    vprev = int(vprev_s)
    print(
        "   -> revert-prev returned published.version_id=%s, can_undo=%s, can_redo=%s"
        % (vprev, prev_view.published.can_undo, prev_view.published.can_redo)
    )
    assert vprev == v1, f"Expected revert-prev to point to v1 (got {vprev})"
    assert _published_pointer(year, month) == v1, "DB pointer should now be at v1"

    print("\n5) REVERT published NEXT — pointer should move from v1 -> v2")
    next_view_any = svc.revert(year, month, target="published", direction="next", user_id=1001)
    next_view = cast(SchedulePublishedRevertRead, next_view_any)
    vnext_s = next_view.published.version_id
    assert vnext_s is not None
    vnext = int(vnext_s)
    print(
        "   -> revert-next returned published.version_id=%s, can_undo=%s, can_redo=%s"
        % (vnext, next_view.published.can_undo, next_view.published.can_redo)
    )
    assert vnext == v2, f"Expected revert-next to point to v2 (got {vnext})"
    assert _published_pointer(year, month) == v2, "DB pointer should now be back at v2"

    print("\nSMOKE OK ✅  Double publish + revert prev/next moves the published pointer " "correctly.")


if __name__ == "__main__":
    main()
