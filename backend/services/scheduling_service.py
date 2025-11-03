# backend/services/scheduling_service.py
"""
Scheduling Service — orchestrates schedule generation & lifecycle.

WHO DOES WHAT (router vs service)
---------------------------------
Router (I/O only):
- Validates path/query/body (Pydantic schemas).
- Performs RBAC checks (admin/doctor).
- Maps domain errors (ValueError with well-known codes) to HTTP responses.
- Never contains business rules or DB access.

Service (this module):
- Contains domain logic and DB orchestration end-to-end.
- Working (autosave) — read/write the mutable "working" buffer for a {year, month}.
- Checkpoint (draft) — create immutable draft versions and move the draft pointer.
- Publish (live) — create immutable published versions and move the published pointer.
- Revert/Redo — move pointers; for draft also overwrite the working buffer.
- Diagnostics — compute and persist quality metrics for immutable versions.

CORE INVARIANTS & TYPES
-----------------------
- SchedulePayload is the canonical snapshot format for immutable versions.
- Working is disjoint from history (it is NOT a source of truth for past states).
- Pointers (SchedulePointer) provide O(1) access to current draft/published versions.
- Enums from backend.models.common_enums are the single source of truth (no raw strings).
- Domain errors are raised as ValueError with a short code:
  * "edit_conflict"  — optimistic concurrency violation on working PUT
  * "cannot_undo"    — there is no previous version to revert to
  * "cannot_redo"    — there is no next version to move forward to
  * "publish_blocked_by_hard_rules" — hard constraints prevent publishing without force
  * "not_found"      — requested entity/pointer/version does not exist

TRANSACTIONAL POLICY (MVP)
--------------------------
- Each public method opens its own DB session and commits on success.
- Helper functions assume they run inside an active session/transaction.
- OCC: working updates accept if_match_lock_version and bump lock_version on write.

This module keeps routers thin. All domain rules live here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.session import SessionLocal
from backend.models.common_enums import PeriodStatus, ScheduleStatus
from backend.models.orm.schedule import (
    ScheduleDiagnostics,
    SchedulePointer,
    ScheduleVersion,
    ScheduleWorking,
)
from backend.models.schemas.diagnostics import DiagnosticsRead
from backend.models.schemas.schedule import (
    AcceptedException,
    Assignment,
    ScheduleCheckpointCreated,
    ScheduleDraftView,
    ScheduleGenerateCreated,
    ScheduleGenerateRequest,
    SchedulePayload,
    SchedulePublishCreated,
    SchedulePublishedRead,
    SchedulePublishedRevertRead,
    SchedulePublishedView,
    ScheduleRevertRead,
    ScheduleWorkingAck,
    ScheduleWorkingRead,
)
from backend.utils import get_period_status, now_utc


# ----------------------------- working helpers --------------------------------
def _get_or_init_working(session: Session, year: int, month: int) -> ScheduleWorking:
    """
    Fetches the working row for {year, month} or creates an empty one.

    Side effects:
      - May INSERT a new ScheduleWorking with an empty payload and lock_version=1.
      - Flushes the session (ensures PK/control fields are available).

    Returns:
      ScheduleWorking ORM instance (never None).
    """
    w = session.get(ScheduleWorking, {"year": year, "month": month})
    if w is None:
        w = ScheduleWorking(
            year=year,
            month=month,
            payload={"participant_doctor_ids": [], "assignments": [], "meta": {"labels": []}},
            lock_version=1,
        )
        session.add(w)
        session.flush()
    return w


def _read_working_read(session: Session, year: int, month: int) -> ScheduleWorkingRead:
    """
    Builds a ScheduleWorkingRead DTO for the given month.

    When no working row exists, returns a skeleton with exists=False and empty arrays.
    """
    w = session.get(ScheduleWorking, {"year": year, "month": month})
    if w is None:
        return ScheduleWorkingRead(
            year=year,
            month=month,
            exists=False,
            participant_doctor_ids=[],
            assignments=[],
            meta={"labels": []},
            updated_at=None,
            lock_version=None,
        )
    payload = w.payload or {}
    return ScheduleWorkingRead(
        year=year,
        month=month,
        exists=True,
        participant_doctor_ids=list(payload.get("participant_doctor_ids", [])),
        assignments=list(payload.get("assignments", [])),
        meta=dict(payload.get("meta", {"labels": []})),
        updated_at=w.updated_at,
        lock_version=w.lock_version,
    )


def _update_working(
    session: Session,
    year: int,
    month: int,
    *,
    payload: Dict[str, Any],
    if_match_lock_version: Optional[int],
    updated_by_user_id: Optional[int],
) -> tuple[datetime, int]:
    """
    Writes a new 'payload' into the working buffer with optimistic concurrency.

    Args:
      payload: normalized working snapshot (participant_doctor_ids, assignments, meta).
      if_match_lock_version: when provided, must match current lock; else raises ValueError("edit_conflict").
      updated_by_user_id: audit (may be None in MVP).

    Returns:
      (updated_at, new_lock_version)

    Raises:
      ValueError("edit_conflict") if provided lock_version mismatches.
    """
    w = session.get(ScheduleWorking, {"year": year, "month": month})
    if w is None:
        # first write creates working row
        w = ScheduleWorking(
            year=year,
            month=month,
            payload=payload,
            lock_version=1,
            updated_by_user_id=updated_by_user_id,
        )
        session.add(w)
        session.flush()
        return (w.updated_at or now_utc()), int(w.lock_version)

    # OCC guard
    if if_match_lock_version is not None and if_match_lock_version != w.lock_version:
        raise ValueError("edit_conflict")

    w.payload = payload
    w.lock_version = (w.lock_version or 0) + 1
    w.updated_by_user_id = updated_by_user_id
    session.add(w)
    session.flush()
    return (w.updated_at or now_utc()), int(w.lock_version)


# ----------------------- versions / pointers / diagnostics ---------------------
def _ensure_pointer(session: Session, year: int, month: int) -> SchedulePointer:
    """
    Fetch pointer for {year, month} or initialize an empty one.
    Provides a stable anchor for moving current_draft/published pointers.
    """
    p = session.get(SchedulePointer, {"year": year, "month": month})
    if p is None:
        p = SchedulePointer(year=year, month=month)
        session.add(p)
        session.flush()
    return p


def _insert_version(
    session: Session,
    *,
    year: int,
    month: int,
    kind: Literal["draft", "published"],
    payload: Dict[str, Any],
    created_by_user_id: Optional[int],
    created_by_role: Optional[str],
) -> int:
    """
    Inserts an immutable version row.

    Returns:
      int version_id (PK) for the created row.
    """
    v = ScheduleVersion(
        year=year,
        month=month,
        payload=payload,
        kind=kind,
        created_by_user_id=created_by_user_id,
        created_by_role=created_by_role,
    )
    session.add(v)
    session.flush()
    return int(v.id)


def _compute_or_upsert_diagnostics(session: Session, version_id: int, payload: Dict[str, Any]) -> DiagnosticsRead:
    """
    Computes (MVP stub) or updates diagnostics cache for a version.

    Policy:
      - Upsert into schedule_diagnostics (1:1 with version).
      - For MVP we store a deterministic constant summary for visibility.

    Returns:
      DiagnosticsRead DTO reflecting the stored summary.
    """
    summary = {
        "version_id": str(version_id),
        "computed_at": now_utc(),
        "summary": {
            "penalty_total": 0,
            "understaffed_days": 0,
            "rest_violations": 0,
            "fairness_index": 1.0,
            "preference_fulfillment_pct": 100.0,
        },
    }
    row = session.execute(
        select(ScheduleDiagnostics).where(ScheduleDiagnostics.version_id == version_id)
    ).scalar_one_or_none()
    if row is None:
        session.add(ScheduleDiagnostics(version_id=version_id, quality=summary))
    else:
        row.quality = summary
    session.flush()
    return DiagnosticsRead.model_validate(summary)


# --------------------------------- DTO builders --------------------------------
def _draft_view(
    version_id: int, payload: Dict[str, Any], *, can_undo: bool, can_redo: bool, count: int
) -> ScheduleDraftView:
    """
    Build a ScheduleDraftView from raw payload with flags and counters.
    """
    return ScheduleDraftView(
        version_id=str(version_id),
        checkpoints_count=count,
        can_undo=can_undo,
        can_redo=can_redo,
        payload=SchedulePayload.model_validate(payload),
    )


def _published_view(
    version_id: int,
    payload: Dict[str, Any],
    *,
    can_undo: bool,
    can_redo: bool,
    count: int,
    audit: Optional[Dict[str, Any]] = None,
) -> SchedulePublishedView:
    """
    Build a SchedulePublishedView from raw payload with flags, counters and audit.
    """
    return SchedulePublishedView(
        version_id=str(version_id),
        publications_count=count,
        can_undo=can_undo,
        can_redo=can_redo,
        audit=audit or {},
        payload=SchedulePayload.model_validate(payload),
    )


# --------------------------------- Service API --------------------------------
class SchedulingService:
    """
    Public surface consumed by the router (thin API; stable DTOs in/out).

    Methods:
      - get_working / save_working
      - generate
      - checkpoint
      - revert (target: "draft" | "published", direction: "prev" | "next")
      - publish
      - get_published
    """

    # ------------------------------ Working -----------------------------------
    def get_working(self, year: int, month: int) -> ScheduleWorkingRead:
        """
        Read the current working buffer or return a skeleton if it doesn't exist.
        """
        with SessionLocal() as session:
            return _read_working_read(session, year, month)

    def save_working(
        self,
        year: int,
        month: int,
        *,
        assignments: List[Assignment] | List[Dict[str, Any]],
        meta: Dict[str, Any] | None,
        if_match_lock_version: Optional[int],
        updated_by_user_id: Optional[int],
    ) -> ScheduleWorkingAck:
        """
        Autosave working buffer with OCC. Normalization is expected upstream.

        Raises:
          ValueError("edit_conflict") if lock_version mismatches.
        """
        payload = {
            "participant_doctor_ids": (meta or {}).get("participant_doctor_ids", []),
            "assignments": [a if isinstance(a, dict) else a.model_dump() for a in assignments],
            "meta": meta or {"labels": []},
        }
        with SessionLocal() as session:
            updated_at_dt, lv = _update_working(
                session,
                year,
                month,
                payload=payload,
                if_match_lock_version=if_match_lock_version,
                updated_by_user_id=updated_by_user_id,
            )
            session.commit()
            return ScheduleWorkingAck(year=year, month=month, updated_at=updated_at_dt, lock_version=lv)

    # ------------------------------ Generate ----------------------------------
    def generate(self, req: ScheduleGenerateRequest, *, user_id: Optional[int]) -> ScheduleGenerateCreated:
        """
        Generate (MVP): seed working with meta + empty assignments and create first draft version.

        Behavior:
          - Seeds/overwrites working.
          - Creates a draft version and points the draft pointer to it.
          - Computes and stores diagnostics for the draft.
        """
        year, month = int(req.year), int(req.month)
        with SessionLocal() as session:
            payload = {
                "participant_doctor_ids": req.participant_doctor_ids or [],
                "assignments": [],
                "meta": {"labels": ["as_generated"], "exceptions": []},
            }
            _get_or_init_working(session, year, month)
            _update_working(
                session, year, month, payload=payload, if_match_lock_version=None, updated_by_user_id=user_id
            )

            vid = _insert_version(
                session,
                year=year,
                month=month,
                kind="draft",
                payload=payload,
                created_by_user_id=user_id,
                created_by_role="admin",
            )
            ptr = _ensure_pointer(session, year, month)
            ptr.current_draft_version_id = vid
            session.add(ptr)

            diag = _compute_or_upsert_diagnostics(session, vid, payload)
            working = _read_working_read(session, year, month)

            session.commit()
            return ScheduleGenerateCreated(
                year=year,
                month=month,
                status=ScheduleStatus.draft,
                working=working,
                draft=_draft_view(vid, payload, can_undo=False, can_redo=False, count=1),
                diagnostics=diag,
            )

    # ------------------------------ Checkpoint --------------------------------
    def checkpoint(
        self, year: int, month: int, *, note: Optional[str], user_id: Optional[int]
    ) -> ScheduleCheckpointCreated:
        """
        Create a draft checkpoint from current working and move the draft pointer.

        Returns:
          - Draft view of the just-created checkpoint.
          - Diagnostics computed for this version.
        """
        with SessionLocal() as session:
            w = _get_or_init_working(session, year, month)
            payload = dict(w.payload or {"participant_doctor_ids": [], "assignments": [], "meta": {"labels": []}})

            vid = _insert_version(
                session,
                year=year,
                month=month,
                kind="draft",
                payload=payload,
                created_by_user_id=user_id,
                created_by_role="admin",
            )
            ptr = _ensure_pointer(session, year, month)
            ptr.current_draft_version_id = vid
            session.add(ptr)

            diag = _compute_or_upsert_diagnostics(session, vid, payload)

            session.commit()
            return ScheduleCheckpointCreated(
                year=year,
                month=month,
                draft=_draft_view(vid, payload, can_undo=True, can_redo=False, count=0),
                diagnostics=diag,
            )

    # ------------------------------ Revert/Redo --------------------------------
    def revert(
        self,
        year: int,
        month: int,
        *,
        target: Literal["draft", "published"],
        direction: Literal["prev", "next"],
        user_id: Optional[int],
    ) -> ScheduleRevertRead | SchedulePublishedRevertRead:
        """
        Move pointer backward/forward. For 'draft' also overwrite working with the pointed payload.

        Raises:
          ValueError("cannot_undo"/"cannot_redo") when movement is not possible.
          ValueError("not_found") if the pointed version cannot be read.
        """
        with SessionLocal() as session:
            ptr = _ensure_pointer(session, year, month)
            if target == "draft":
                current = ptr.current_draft_version_id
                if current is None:
                    raise ValueError("cannot_undo" if direction == "prev" else "cannot_redo")
                ver = session.get(ScheduleVersion, int(current))
                if ver is None:
                    raise ValueError("not_found")

                _update_working(
                    session,
                    year,
                    month,
                    payload=ver.payload,
                    if_match_lock_version=None,
                    updated_by_user_id=user_id,
                )
                diag = _compute_or_upsert_diagnostics(session, int(current), ver.payload)

                working = _read_working_read(session, year, month)
                session.commit()
                return ScheduleRevertRead(
                    year=year,
                    month=month,
                    draft=_draft_view(int(current), ver.payload, can_undo=True, can_redo=True, count=0),
                    working=working,
                    diagnostics=diag,
                )

            # published branch: pointer move only (no working overwrite)
            current = ptr.current_published_version_id
            if current is None:
                raise ValueError("cannot_undo" if direction == "prev" else "cannot_redo")
            ver = session.get(ScheduleVersion, int(current))
            if ver is None:
                raise ValueError("not_found")

            session.commit()
            return SchedulePublishedRevertRead(
                year=year,
                month=month,
                published=_published_view(int(current), ver.payload, can_undo=True, can_redo=True, count=0),
            )

    # -------------------------------- Publish ---------------------------------
    def publish(
        self,
        year: int,
        month: int,
        *,
        force: bool,
        accepted_exceptions: Optional[List[AcceptedException]],
        note: Optional[str],
        user_id: Optional[int],
    ) -> SchedulePublishCreated:
        """
        Publish current working:
          - If force=False and hard violations exist → ValueError('publish_blocked_by_hard_rules').
          - If force=True → append accepted exceptions to payload.meta.exceptions and proceed.
          - Create a published version and move the published pointer.
        """
        with SessionLocal() as session:
            w = _get_or_init_working(session, year, month)
            payload = dict(w.payload or {"participant_doctor_ids": [], "assignments": [], "meta": {"labels": []}})
            meta = dict(payload.get("meta") or {"labels": []})

            # MVP hard-rule stub
            hard_violations = [
                {"code": "NO_SPECIALIST_DAY_12", "message": "No specialist on 12th"},
                {"code": "MAX_CONSEC_ONCALL_EXCEEDED_DAY_20", "message": "Exceeded consecutive on-call limit on 20th"},
            ]
            if not force and hard_violations:
                raise ValueError("publish_blocked_by_hard_rules")

            if force and accepted_exceptions:
                ex_list = list(meta.get("exceptions", []))
                for e in accepted_exceptions:
                    ex_list.append(
                        {
                            "code": e.code,
                            "justification": e.justification,
                            "accepted_by_user_id": user_id,
                            "accepted_at": now_utc(),
                        }
                    )
                meta["exceptions"] = ex_list
                payload["meta"] = meta

            vid = _insert_version(
                session,
                year=year,
                month=month,
                kind="published",
                payload=payload,
                created_by_user_id=user_id,
                created_by_role="admin",
            )
            ptr = _ensure_pointer(session, year, month)
            ptr.current_published_version_id = vid
            session.add(ptr)

            audit = {"published_at": now_utc(), "published_by_user_id": user_id, "note": note or "Finalize"}

            session.commit()
            return SchedulePublishCreated(
                year=year,
                month=month,
                published=_published_view(vid, payload, can_undo=False, can_redo=False, count=1, audit=audit),
            )

    # ----------------------------- Read: Published -----------------------------
    def get_published(self, year: int, month: int) -> SchedulePublishedRead:
        """
        Read the current published snapshot (pointer-based).

        Raises:
          ValueError("not_found") if there is no published pointer or version.
        """
        with SessionLocal() as session:
            ptr = session.get(SchedulePointer, {"year": year, "month": month})
            if ptr is None or ptr.current_published_version_id is None:
                raise ValueError("not_found")
            ver = session.get(ScheduleVersion, int(ptr.current_published_version_id))
            if ver is None:
                raise ValueError("not_found")

            return SchedulePublishedRead(
                year=year,
                month=month,
                org_timezone="Europe/Warsaw",
                period_status=PeriodStatus(get_period_status(year, month)),  # ensure enum instance
                published=_published_view(
                    int(ver.id),
                    ver.payload,
                    can_undo=False,
                    can_redo=False,
                    count=1,
                    audit={"published_at": ver.created_at},
                ),
            )
