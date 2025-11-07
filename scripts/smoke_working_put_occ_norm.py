# scripts/smoke_occ_working_put.py
"""
Smoke Test: OCC + Working PUT semantics for SchedulingService

What this script verifies
-------------------------
1) OCC (Optimistic Concurrency Control):
   - Reads 'lock_version' from the current working snapshot.
   - Performs PUT /working with a correct 'if_match_lock_version' -> succeeds and bumps lock_version.
   - Attempts PUT /working again with the stale (old) lock -> raises ValueError("edit_conflict").

2) Autosave semantics for participant_doctor_ids:
   - PUT /working MUST NOT modify 'participant_doctor_ids'.
   - Even if the client tries to sneak 'participant_doctor_ids' in meta, the service ignores it.

3) Normalization on write:
   - Assignments: sorted & deduped by (day, shift_type, doctor_id).
   - Meta.labels: unique & sorted.

What this script DOES
---------------------
- Wipes the target period {year, month} from schedule tables (versions, working, pointer)
  so the test is idempotent and safe to re-run.
- Calls SchedulingService.generate(...) to seed working with participant_doctor_ids [1, 2]
  and create the first draft checkpoint.
- Reads the working 'lock_version' and uses it to test OCC semantics and normalization.

What this script DOES NOT DO
----------------------------
- It does not perform HTTP requests. It uses the service class directly.
- It does not cover export/diagnostics beyond what SchedulingService already invokes.

How to run
----------
1) Ensure your Python environment is set up and the project is importable (e.g., run from repo root).
2) Make sure SQLite dev DB is reachable (default path in your project).
3) Run:
    python -m scripts.smoke_occ_working_put

Expected output (high level)
----------------------------
- "WIPE current period state"
- "GENERATE — seed working with participant_doctor_ids [1, 2]" -> working.exists True
- "READ working — capture lock_version for OCC" -> lock_version = N
- "SAVE working (PUT) ..." -> updated_at printed, new lock_version = N+1
- "READ working — verify participants preserved + normalization"
  * participants remain [1, 2]
  * assignments printed in sorted, deduped order
  * labels printed unique & sorted
- "SAVE working (PUT) again with STALE lock_version — expect edit_conflict"
  * raises ValueError("edit_conflict")
- "SMOKE OK ✅  OCC works, participants preserved, normalization applied."

WARNING
-------
This script deletes schedule data for the chosen {year, month}. Do not point it at
a period you want to keep. Adjust the 'year' and 'month' constants below if needed.
"""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import delete, select

from backend.db.session import SessionLocal
from backend.models.orm.schedule import SchedulePointer, ScheduleVersion, ScheduleWorking
from backend.models.schemas.schedule import Assignment, ScheduleGenerateRequest
from backend.services.scheduling_service import SchedulingService


def _wipe_period(year: int, month: int) -> None:
    """Idempotently remove all schedule records for the given {year, month}.

    This ensures the smoke test starts from a clean state and can be re-run without
    manual cleanup. It deletes:
      - all ScheduleVersion rows for the period (both 'draft' and 'published'),
      - the ScheduleWorking row,
      - the SchedulePointer row.
    """
    with SessionLocal() as s:
        # delete versions (draft+published), then working & pointer
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
    """Run the smoke steps and assert expected invariants.

    Steps:
      0) Wipe the period state.
      1) generate(...) → working exists with participants [1, 2].
      2) read working → capture lock_version (N).
      3) save_working with correct if_match_lock_version=N:
           - normalizes assignments & meta.labels,
           - preserves participant_doctor_ids,
           - bumps lock_version to N+1.
      4) read working → assert invariants.
      5) save_working with stale if_match_lock_version=N → expect ValueError("edit_conflict").
    """
    svc = SchedulingService()

    # Adjust if needed; the script wipes this period.
    year, month = 2025, 12

    print("0) WIPE current period state")
    _wipe_period(year, month)

    print("1) GENERATE — seed working with participant_doctor_ids [1, 2]")
    gen_req = ScheduleGenerateRequest(year=year, month=month, participant_doctor_ids=[1, 2])
    gen_out = svc.generate(gen_req, user_id=1001)
    assert gen_out.working.exists is True
    assert gen_out.working.participant_doctor_ids == [1, 2]
    print(f"   -> draft id: {gen_out.draft.version_id}, participants: {gen_out.working.participant_doctor_ids}")

    print("\n2) READ working — capture lock_version for OCC")
    w1 = svc.get_working(year, month)
    assert w1.exists and isinstance(w1.lock_version, int)
    lock_v1 = int(w1.lock_version)
    print(f"   -> lock_version: {lock_v1}")

    print("\n3) SAVE working (PUT) with messy assignments & meta trying to inject participant_doctor_ids=[999]")
    # messy input: duplicates and unsorted
    messy_assignments: List[Dict[str, Any]] = [
        {"day": 2, "shift_type": "on_call", "doctor_id": 2},
        {"day": 1, "shift_type": "on_duty", "doctor_id": 1},
        {"day": 1, "shift_type": "on_duty", "doctor_id": 1},  # duplicate
        {"day": 1, "shift_type": "on_call", "doctor_id": 2},
    ]
    # meta tries to sneak in participant_doctor_ids (should be ignored by service)
    meta = {"labels": ["z", "a", "a"], "participant_doctor_ids": [999]}

    ack = svc.save_working(
        year,
        month,
        assignments=[Assignment(**a) for a in messy_assignments],
        meta=meta,
        if_match_lock_version=lock_v1,  # correct OCC
        updated_by_user_id=1001,
    )
    print(f"   -> updated_at: {ack.updated_at}, new lock_version: {ack.lock_version}")

    print("\n4) READ working — verify participants preserved + normalization")
    w2 = svc.get_working(year, month)
    print(f"   -> participants: {w2.participant_doctor_ids}")
    print(f"   -> assignments: {w2.assignments}")
    print(f"   -> labels: {w2.meta.get('labels')}")
    # participants unchanged
    assert w2.participant_doctor_ids == [1, 2], "PUT must not change participant_doctor_ids"
    # assignments normalized (sorted & deduped)
    expected_assignments = [
        {"day": 1, "shift_type": "on_call", "doctor_id": 2},
        {"day": 1, "shift_type": "on_duty", "doctor_id": 1},
        {"day": 2, "shift_type": "on_call", "doctor_id": 2},
    ]
    got = [dict(a) for a in (w2.assignments or [])]
    assert got == expected_assignments, f"Assignments not normalized: {got}"
    # labels normalized
    assert w2.meta.get("labels") == ["a", "z"], "Labels should be unique & sorted"
    # lock bumped
    assert int(w2.lock_version or 0) == lock_v1 + 1, "Lock version should increment"

    print("\n5) SAVE working (PUT) again with STALE lock_version — expect edit_conflict")
    try:
        _ = svc.save_working(
            year,
            month,
            assignments=[],  # no-op change
            meta={"labels": ["b"]},
            if_match_lock_version=lock_v1,  # stale on purpose
            updated_by_user_id=1001,
        )
        raise AssertionError("Expected ValueError('edit_conflict') but call succeeded")
    except ValueError as e:
        assert str(e) == "edit_conflict", f"Unexpected error: {e}"
        print("   -> got expected ValueError('edit_conflict')")

    print("\nSMOKE OK ✅  OCC works, participants preserved, normalization applied.")


if __name__ == "__main__":
    main()
