# scripts/smoke_flow_checkpoint_undo_redo_publish_revert.py
"""
Smoke Test: Checkpoint + Draft Undo/Redo + Publish/Revert for SchedulingService

What this script verifies
-------------------------
1) Checkpoint behavior (draft snapshots):
   - Creating a checkpoint captures the current working payload as an immutable draft.
   - Snapshot normalization: assignments are sorted & deduped; meta.labels are unique & sorted.
   - Pointer semantics: after a new checkpoint, the draft pointer moves to the NEWEST id
     (i.e., no REDO available immediately after a checkpoint).

2) Draft Undo/Redo:
   - revert(target="draft", direction="prev"/"next") moves the draft pointer
     and overwrites the working buffer with that snapshot.
   - can_undo/can_redo flags and checkpoints_count reflect the current pointer position.

3) Publish & Revert (published stream):
   - publish(...) creates a published version and moves the published pointer to it.
   - Re-publishing creates a newer published version (higher id).
   - revert(target="published", ...) moves the published pointer only (no working overwrite).

How to run
----------
python -m scripts.smoke_flow_checkpoint_undo_redo_publish_revert
"""

from __future__ import annotations

from typing import Any, Dict, List, cast

from sqlalchemy import delete, select

from backend.db.session import SessionLocal
from backend.models.common_enums import ShiftType
from backend.models.orm.schedule import SchedulePointer, ScheduleVersion, ScheduleWorking
from backend.models.schemas.schedule import (
    Assignment,
    ScheduleGenerateRequest,
    SchedulePublishedRevertRead,
    ScheduleRevertRead,
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
    """Run the smoke steps for checkpoint/draft undo-redo and publish/revert."""
    svc = SchedulingService()

    # Adjust if needed; the script wipes this period.
    year, month = 2026, 1

    print("0) WIPE current period state")
    _wipe_period(year, month)

    print("1) GENERATE — seed working with participant_doctor_ids [1, 2, 3]")
    gen = svc.generate(ScheduleGenerateRequest(year=year, month=month, participant_doctor_ids=[1, 2, 3]), user_id=42)
    assert gen.working and gen.working.exists, "Working should exist after generate()"
    assert gen.working.participant_doctor_ids == [1, 2, 3]
    print(f"   -> draft id: {gen.draft.version_id}, participants: {gen.working.participant_doctor_ids}")

    print("\n2) SAVE working with messy assignments + duplicate labels (service will normalize)")
    messy_assignments: List[Dict[str, Any]] = [
        {"day": 2, "shift_type": ShiftType.oncall, "doctor_id": 2},
        {"day": 1, "shift_type": ShiftType.onsite, "doctor_id": 1},
        {"day": 1, "shift_type": ShiftType.onsite, "doctor_id": 1},  # duplicate
        {"day": 1, "shift_type": ShiftType.oncall, "doctor_id": 2},
    ]
    w = svc.get_working(year, month)
    assert w.lock_version is not None, "Expected non-null lock_version for OCC"
    ack = svc.save_working(
        year,
        month,
        assignments=[Assignment(**a) for a in messy_assignments],
        meta={"labels": ["draft", "a", "a"]},
        if_match_lock_version=w.lock_version,
        updated_by_user_id=42,
    )
    print(f"   -> save OK, new lock_version: {ack.lock_version}")

    print("\n3) CHECKPOINT #1 — should normalize snapshot, pointer at newest, no REDO")
    cp1 = svc.checkpoint(year, month, note="first", user_id=42)
    draft1_id_s = cp1.draft.version_id
    assert draft1_id_s is not None, "draft.version_id should not be None"
    draft1_id = int(cast(str, draft1_id_s))
    print(f"   -> draft#1 id: {draft1_id}, checkpoints_count: {cp1.draft.checkpoints_count}")
    print(f"   -> can_undo: {cp1.draft.can_undo}, can_redo: {cp1.draft.can_redo}")

    assert cp1.draft.payload is not None, "draft.payload should not be None"
    snap1_asg = [dict(a) for a in (cp1.draft.payload.assignments or [])]
    expected_sorted = [
        {"day": 1, "shift_type": "on_call", "doctor_id": 2},
        {"day": 1, "shift_type": "on_duty", "doctor_id": 1},
        {"day": 2, "shift_type": "on_call", "doctor_id": 2},
    ]
    assert snap1_asg == expected_sorted, f"Draft#1 assignments not normalized: {snap1_asg}"
    assert (cp1.draft.payload.meta or {}).get("labels") == ["a", "draft"], "Labels should be unique & sorted"
    assert cp1.draft.can_redo is False, "After a new checkpoint there must be no REDO"

    print("\n4) Mutate working slightly and CHECKPOINT #2 — pointer moves to newest, no REDO")
    w2 = svc.get_working(year, month)
    assert w2.lock_version is not None
    typed_expected_sorted = [
        {"day": a["day"], "shift_type": ShiftType(a["shift_type"]), "doctor_id": a["doctor_id"]}
        for a in expected_sorted
    ]
    ack2 = svc.save_working(
        year,
        month,
        assignments=[
            *[Assignment(**a) for a in typed_expected_sorted],
            Assignment(day=2, shift_type=ShiftType.onsite, doctor_id=3),
        ],
        meta={"labels": ["draft", "b"]},
        if_match_lock_version=w2.lock_version,
        updated_by_user_id=42,
    )
    print(f"   -> save #2 OK, new lock_version: {ack2.lock_version}")

    cp2 = svc.checkpoint(year, month, note="second", user_id=42)
    draft2_id_s = cp2.draft.version_id
    assert draft2_id_s is not None, "draft.version_id should not be None"
    draft2_id = int(cast(str, draft2_id_s))
    print(f"   -> draft#2 id: {draft2_id}, checkpoints_count: {cp2.draft.checkpoints_count}")
    print(f"   -> can_undo: {cp2.draft.can_undo}, can_redo: {cp2.draft.can_redo}")
    assert draft2_id > draft1_id, "Second draft id should be greater (newest)"
    assert cp2.draft.can_redo is False, "Newest checkpoint must have no REDO"

    assert cp2.draft.payload is not None, "draft.payload should not be None"
    snap2_asg = [dict(a) for a in (cp2.draft.payload.assignments or [])]
    expected2 = [
        {"day": 1, "shift_type": "on_call", "doctor_id": 2},
        {"day": 1, "shift_type": "on_duty", "doctor_id": 1},
        {"day": 2, "shift_type": "on_call", "doctor_id": 2},
        {"day": 2, "shift_type": "on_duty", "doctor_id": 3},
    ]
    assert snap2_asg == expected2, f"Draft#2 assignments not as expected: {snap2_asg}"
    assert (cp2.draft.payload.meta or {}).get("labels") == ["b", "draft"], "Labels should be unique & sorted"

    print("\n5) REVERT draft PREV — pointer moves to draft#1 and overwrites working")
    rv_prev_draft = svc.revert(year, month, target="draft", direction="prev", user_id=42)
    # rv_prev_draft: ScheduleRevertRead
    assert isinstance(rv_prev_draft, ScheduleRevertRead)
    assert rv_prev_draft.draft.version_id == str(draft1_id), "Pointer should move to draft#1"
    assert rv_prev_draft.working is not None, "working should not be None in draft revert"
    w_after_prev = rv_prev_draft.working
    assert [dict(a) for a in (w_after_prev.assignments or [])] == expected_sorted, "Working not overwritten by draft#1"
    print(f"   -> moved to draft#1, can_undo: {rv_prev_draft.draft.can_undo}, can_redo: {rv_prev_draft.draft.can_redo}")

    print("\n6) REVERT draft NEXT — pointer moves back to draft#2 and overwrites working")
    rv_next_draft = svc.revert(year, month, target="draft", direction="next", user_id=42)
    assert isinstance(rv_next_draft, ScheduleRevertRead)
    assert rv_next_draft.draft.version_id == str(draft2_id), "Pointer should move back to draft#2"
    assert rv_next_draft.working is not None, "working should not be None in draft revert"
    w_after_next = rv_next_draft.working
    assert [dict(a) for a in (w_after_next.assignments or [])] == expected2, "Working not overwritten by draft#2"
    print(f"   -> moved to draft#2, can_undo: {rv_next_draft.draft.can_undo}, can_redo: {rv_next_draft.draft.can_redo}")

    print("\n7) PUBLISH #1 — create first published version from current working/draft")
    pub1 = svc.publish(year, month, force=False, accepted_exceptions=None, note="go-live #1", user_id=42)
    pub1_id_s = pub1.published.version_id
    assert pub1_id_s is not None
    pub1_id = int(cast(str, pub1_id_s))
    print(f"   -> published#1 id: {pub1_id}, publications_count: {pub1.published.publications_count}")
    assert pub1.published.can_undo is False, "Only one publication yet -> no undo"
    assert pub1.published.can_redo is False, "Only one publication yet -> no redo"

    print("\n8) Mutate working again and PUBLISH #2 — then revert published PREV/NEXT")
    w3 = svc.get_working(year, month)
    assert w3.lock_version is not None
    _ = svc.save_working(
        year,
        month,
        assignments=[
            Assignment(day=1, shift_type=ShiftType.oncall, doctor_id=2),
            Assignment(day=1, shift_type=ShiftType.onsite, doctor_id=1),
            Assignment(day=2, shift_type=ShiftType.oncall, doctor_id=3),  # changed doctor on on-call
            Assignment(day=2, shift_type=ShiftType.onsite, doctor_id=3),
        ],
        meta={"labels": ["live", "draft"]},
        if_match_lock_version=w3.lock_version,
        updated_by_user_id=42,
    )

    pub2 = svc.publish(year, month, force=False, accepted_exceptions=None, note="go-live #2", user_id=42)
    pub2_id_s = pub2.published.version_id
    assert pub2_id_s is not None
    pub2_id = int(cast(str, pub2_id_s))
    print(f"   -> published#2 id: {pub2_id}, publications_count: {pub2.published.publications_count}")
    assert pub2_id > pub1_id, "Second publication id should be newer"

    # Revert published PREV (to pub#1) – returns SchedulePublishedRevertRead (only .published)
    rv_pub_prev = svc.revert(year, month, target="published", direction="prev", user_id=42)
    assert isinstance(rv_pub_prev, SchedulePublishedRevertRead)
    print(f"   -> revert published PREV -> now at version_id: {rv_pub_prev.published.version_id}")
    assert rv_pub_prev.published.version_id == str(pub1_id)
    assert rv_pub_prev.published.can_redo is True, "After moving back, redo should be possible"

    # Revert published NEXT (back to pub#2)
    rv_pub_next = svc.revert(year, month, target="published", direction="next", user_id=42)
    assert isinstance(rv_pub_next, SchedulePublishedRevertRead)
    print(f"   -> revert published NEXT -> now at version_id: {rv_pub_next.published.version_id}")
    assert rv_pub_next.published.version_id == str(pub2_id)

    print("\nSMOKE OK ✅  checkpoint/undo/redo/publish/revert flow works.")


if __name__ == "__main__":
    main()
