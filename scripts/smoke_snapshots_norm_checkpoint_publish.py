# scripts/smoke_snapshots_checkpoint_publish.py
"""
Smoke Test: Snapshot normalization for checkpoint() and publish()

What this script verifies
-------------------------
1) checkpoint():
   - Takes the current working payload and persists a *draft* version.
   - The persisted version payload is normalized via `_normalize_snapshot_payload(...)`:
       * assignments are sorted & deduped (day, shift_type, doctor_id),
       * shift_type values are plain strings ("on_duty"|"on_call"), not Enums,
       * meta.labels are unique & sorted.

   - Draft pointer is moved to the newest id; by construction `can_redo == False`.

2) publish():
   - Takes the current working payload and persists a *published* version.
   - The persisted version payload is normalized the same way as for checkpoint.
   - Published pointer is set to the newest id.

What this script DOES
---------------------
- Wipes the target period {year, month}.
- generate() -> seeds participants and a first draft.
- save_working() with intentionally messy assignments/meta to ensure cleanup is needed.
- checkpoint() -> reads the just-created version from DB and asserts normalization.
- publish()   -> reads the just-created version from DB and asserts normalization.

What this script DOES NOT DO
----------------------------
- It does not hit HTTP endpoints; it uses the service class directly.
- It does not test hard-rule violations (the current stub returns no violations).
- It does not test redo/undo beyond the simple "redo cleared" check on draft.

How to run
----------
python -m scripts.smoke_snapshots_checkpoint_publish

WARNING
-------
This script deletes schedule data for the chosen {year, month}. Adjust constants if needed.
"""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import delete, select

from backend.db.session import SessionLocal
from backend.models.orm.schedule import SchedulePointer, ScheduleVersion, ScheduleWorking
from backend.models.schemas.schedule import Assignment, ScheduleGenerateRequest
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


def _fetch_version_payload(version_id: int | str) -> Dict[str, Any]:
    """Helper: return the raw JSON payload for a given ScheduleVersion.id (accepts int or string id)."""
    with SessionLocal() as s:
        v = s.get(ScheduleVersion, int(version_id))
        assert v is not None, f"Version {version_id} not found"
        return dict(v.payload or {})


def main() -> None:
    svc = SchedulingService()

    # Adjust if needed; the script wipes this period.
    year, month = 2025, 12

    print("0) WIPE current period state")
    _wipe_period(year, month)

    print("1) GENERATE — seed working with participant_doctor_ids [1, 2, 3]")
    gen_req = ScheduleGenerateRequest(year=year, month=month, participant_doctor_ids=[1, 2, 3])
    gen_out = svc.generate(gen_req, user_id=1001)
    assert gen_out.working.exists is True
    print(f"   -> draft id: {gen_out.draft.version_id}")

    print("\n2) SAVE working with messy data (duplicates, unsorted, labels with dup)")
    messy_assignments: List[Dict[str, Any]] = [
        {"day": 2, "shift_type": "on_call", "doctor_id": 3},
        {"day": 1, "shift_type": "on_duty", "doctor_id": 1},
        {"day": 1, "shift_type": "on_duty", "doctor_id": 1},  # duplicate
        {"day": 1, "shift_type": "on_call", "doctor_id": 2},
    ]
    w1 = svc.get_working(year, month)
    ack = svc.save_working(
        year,
        month,
        assignments=[Assignment(**a) for a in messy_assignments],
        meta={"labels": ["z", "a", "a"]},
        if_match_lock_version=int(w1.lock_version or 0),
        updated_by_user_id=1001,
    )
    print(f"   -> working saved; lock_version now {ack.lock_version}")

    print("\n3) CHECKPOINT — create a draft snapshot and assert normalization")
    cp = svc.checkpoint(year, month, note=None, user_id=1001)
    draft_id_s = cp.draft.version_id
    assert draft_id_s is not None, "Draft version_id should not be None"
    draft_id = int(draft_id_s)
    print(f"   -> draft created: version_id={draft_id}; can_redo={cp.draft.can_redo}")
    assert cp.draft.can_redo is False, "New checkpoint must clear REDO (no 'next')"

    # Read back the persisted version payload from DB
    draft_payload = _fetch_version_payload(draft_id)

    # Expected normalized shape
    expected_assignments = [
        {"day": 1, "shift_type": "on_call", "doctor_id": 2},
        {"day": 1, "shift_type": "on_duty", "doctor_id": 1},
        {"day": 2, "shift_type": "on_call", "doctor_id": 3},
    ]
    assert (
        draft_payload.get("assignments") == expected_assignments
    ), f"Draft not normalized: {draft_payload.get('assignments')}"
    labels = draft_payload.get("meta", {}).get("labels")
    assert labels == ["a", "z"], f"Draft labels not normalized: {labels}"
    # ensure no Enum artifacts in shift_type
    assert all(
        isinstance(a["shift_type"], str) and a["shift_type"] in {"on_call", "on_duty"}
        for a in draft_payload.get("assignments", [])
    ), "Draft contains non-string or invalid shift_type values"

    print("   -> draft snapshot normalized ✅")

    print("\n4) PUBLISH — create a published snapshot and assert normalization")
    pub = svc.publish(year, month, force=False, accepted_exceptions=None, note=None, user_id=1001)
    pub_id_s = pub.published.version_id
    assert pub_id_s is not None, "Published version_id should not be None"
    pub_id = int(pub_id_s)
    print(f"   -> published created: version_id={pub_id}")

    # Read back the persisted published payload from DB
    published_payload = _fetch_version_payload(pub_id)
    # Given working hasn't changed since checkpoint, the normalization should match
    assert (
        published_payload.get("assignments") == expected_assignments
    ), f"Published not normalized: {published_payload.get('assignments')}"
    plabels = published_payload.get("meta", {}).get("labels")
    assert plabels == ["a", "z"], f"Published labels not normalized: {plabels}"
    assert all(
        isinstance(a["shift_type"], str) and a["shift_type"] in {"on_call", "on_duty"}
        for a in published_payload.get("assignments", [])
    ), "Published contains non-string or invalid shift_type values"

    print("   -> published snapshot normalized ✅")

    print("\nSMOKE OK ✅  Checkpoint & Publish snapshots are normalized via _normalize_snapshot_payload.")


if __name__ == "__main__":
    main()
