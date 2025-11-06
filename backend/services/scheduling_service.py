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

from sqlalchemy import delete, func, select
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

# Retention policy (FIFO): tune here
# Change these to keep more/fewer historical snapshots.
RETAIN_LAST_DRAFTS = 5
RETAIN_LAST_PUBLISHED = 5


# -------------------------- period edit-window helper --------------------------
def _ensure_editable(year: int, month: int) -> None:
    """
    Enforce the admin editing window (current/future only) in the org timezone.

    IMPORTANT (development mode):
    - Currently a NO-OP to keep development and tests unblocked.
    - To enable enforcement later, uncomment lines below.

    Raises:
        ValueError("period_closed"): when the period is in the past.
    """
    # status = PeriodStatus(get_period_status(year, month))
    # if status == PeriodStatus.past:
    #     raise ValueError("period_closed")
    return


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


def _drafts_total(session: Session, year: int, month: int) -> int:
    """
    Count how many draft versions exist for a given {year, month}.
    """
    return (
        session.scalar(
            select(func.count(ScheduleVersion.id)).where(
                ScheduleVersion.year == year,
                ScheduleVersion.month == month,
                ScheduleVersion.kind == "draft",
            )
        )
        or 0
    )


def _draft_neighbors(session: Session, year: int, month: int, current_id: int) -> tuple[bool, bool]:
    """
    For the current draft (current_id) within {year, month}, return (has_prev, has_next).
    Ordering is by increasing version id; snapshots are immutable.
    """
    older = session.scalar(
        select(func.max(ScheduleVersion.id)).where(
            ScheduleVersion.year == year,
            ScheduleVersion.month == month,
            ScheduleVersion.kind == "draft",
            ScheduleVersion.id < current_id,
        )
    )
    newer = session.scalar(
        select(func.min(ScheduleVersion.id)).where(
            ScheduleVersion.year == year,
            ScheduleVersion.month == month,
            ScheduleVersion.kind == "draft",
            ScheduleVersion.id > current_id,
        )
    )
    return (older is not None, newer is not None)


def _published_total(session: Session, year: int, month: int) -> int:
    """
    Count how many published versions exist for a given {year, month}.
    """
    return (
        session.scalar(
            select(func.count(ScheduleVersion.id)).where(
                ScheduleVersion.year == year,
                ScheduleVersion.month == month,
                ScheduleVersion.kind == "published",
            )
        )
        or 0
    )


def _published_neighbors(session: Session, year: int, month: int, current_id: int) -> tuple[bool, bool]:
    """
    Return (has_prev, has_next) for the current published version within {year, month}.
    - has_prev: exists published with id < current_id
    - has_next: exists published with id > current_id
    """
    # any older?
    older = session.scalar(
        select(func.max(ScheduleVersion.id)).where(
            ScheduleVersion.year == year,
            ScheduleVersion.month == month,
            ScheduleVersion.kind == "published",
            ScheduleVersion.id < current_id,
        )
    )
    # any newer?
    newer = session.scalar(
        select(func.min(ScheduleVersion.id)).where(
            ScheduleVersion.year == year,
            ScheduleVersion.month == month,
            ScheduleVersion.kind == "published",
            ScheduleVersion.id > current_id,
        )
    )
    return (older is not None, newer is not None)


def _prune_drafts(session: Session, year: int, month: int, *, keep_last: int = 5) -> None:
    """
    Retain only the newest `keep` draft versions for {year, month}.
    - Delete oldest overflow versions (and their diagnostics).
    - If pointer points to a deleted version, move it to the newest remaining; or None if none left.
    Implementation notes:
    - Order by increasing `id` (creation order).
    - Delete diagnostics first to satisfy FK constraints if present.
    """
    if keep_last <= 0:
        return

    # Collect all draft ids ascending (oldest first)
    ids = session.scalars(
        select(ScheduleVersion.id)
        .where(
            ScheduleVersion.year == year,
            ScheduleVersion.month == month,
            ScheduleVersion.kind == "draft",
        )
        .order_by(ScheduleVersion.id.asc())
    ).all()

    overflow = max(0, len(ids) - keep_last)
    if overflow <= 0:
        return

    to_delete = ids[:overflow]
    remaining = ids[overflow:]

    # Delete diagnostics for to-be-deleted versions
    if to_delete:
        session.execute(delete(ScheduleDiagnostics).where(ScheduleDiagnostics.version_id.in_(to_delete)))
        session.execute(delete(ScheduleVersion).where(ScheduleVersion.id.in_(to_delete)))

    # Fix pointer if needed
    ptr = _ensure_pointer(session, year, month)
    if ptr.current_draft_version_id and int(ptr.current_draft_version_id) in to_delete:
        ptr.current_draft_version_id = remaining[-1] if remaining else None
        session.add(ptr)


def _prune_published(session: Session, year: int, month: int, *, keep_last: int = 5) -> None:
    """
    Retain only the newest `keep` published versions for {year, month}.
    - Delete oldest overflow versions (and their diagnostics).
    - If pointer points to a deleted version, move it to the newest remaining; or None if none left.
    Implementation notes mirror _prune_drafts.
    """
    if keep_last <= 0:
        return

    ids = session.scalars(
        select(ScheduleVersion.id)
        .where(
            ScheduleVersion.year == year,
            ScheduleVersion.month == month,
            ScheduleVersion.kind == "published",
        )
        .order_by(ScheduleVersion.id.asc())
    ).all()

    overflow = max(0, len(ids) - keep_last)
    if overflow <= 0:
        return

    to_delete = ids[:overflow]
    remaining = ids[overflow:]

    if to_delete:
        session.execute(delete(ScheduleDiagnostics).where(ScheduleDiagnostics.version_id.in_(to_delete)))
        session.execute(delete(ScheduleVersion).where(ScheduleVersion.id.in_(to_delete)))

    ptr = _ensure_pointer(session, year, month)
    if ptr.current_published_version_id and int(ptr.current_published_version_id) in to_delete:
        ptr.current_published_version_id = remaining[-1] if remaining else None
        session.add(ptr)


def _compute_or_upsert_diagnostics(session: Session, version_id: int, payload: Dict[str, Any]) -> DiagnosticsRead:
    """
    Compute (MVP stub) or upsert diagnostics cache for a given schedule version.

    Design:
    - Store only plain analytics under JSON column `quality` (no datetimes inside JSON).
    - Keep timestamps in the dedicated DB column `computed_at`.
    - Ensure 1:1 relation per version_id (upsert behavior).
    """

    # JSON payload must contain only JSON-serializable primitives.
    quality_payload: Dict[str, Any] = {
        "summary": {
            "penalty_total": 0,
            "understaffed_days": 0,
            "rest_violations": 0,
            "fairness_index": 1.0,
            "preference_fulfillment_pct": 100.0,
        }
        # NOTE: DO NOT put `computed_at` or `version_id` here — keep them as columns/fields, not in JSON.
    }

    # Try to fetch existing diagnostics row for this version
    row = session.execute(
        select(ScheduleDiagnostics).where(ScheduleDiagnostics.version_id == version_id)
    ).scalar_one_or_none()

    if row is None:
        # Insert new row; computed_at should be handled by DB default or ORM default
        row = ScheduleDiagnostics(version_id=version_id, quality=quality_payload)
        session.add(row)
    else:
        # Update existing row's quality JSON
        row.quality = quality_payload

    # Flush to get DB-generated values (e.g., computed_at, id)
    session.flush()

    # Build and return the DTO; Pydantic will serialize datetime to ISO8601 automatically
    return DiagnosticsRead(
        version_id=str(version_id),
        computed_at=row.computed_at,
        summary=quality_payload["summary"],
    )


# ------------------------------ validation helpers -----------------------------
def _hard_rule_violations(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Evaluate hard (non-overridable) rule violations for a schedule payload.

    Production intent:
    - This function should run deterministic validations derived from domain rules
      (e.g., legal staffing minima, rest-period hard constraints).
    - Return a list of {code, message} dicts. Empty list means "no hard violations".

    Current behavior (MVP):
    - Returns an empty list to keep publishing unblocked during development.
    - Replace with real checks once the solver/validator is wired into the service.
    """
    return []


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
        Autosave the working buffer with optimistic concurrency (OCC).
        Scope:
            - Writes ONLY the mutable 'working' snapshot for {year, month}.
            - Does NOT create a checkpoint (history remains unchanged).
        OCC:
            - If 'if_match_lock_version' is provided and mismatches current lock,
              raise ValueError("edit_conflict").
        Edit window:
            - A past-period edit guard exists but is currently DISABLED for development.
              To enable later, uncomment the _ensure_editable(...) call below.
        Normalization:
            - Deterministic normalization (sort & dedupe of assignments, labels cleanup)
              will be enforced inside the service in the next step.
            - Currently, inputs are persisted largely as-is to keep development simple.

        """
        # _ensure_editable(year, month)  # Enable later to block edits on past periods

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

        Invariant (clear REDO semantics):
          - A newly created checkpoint is always the max(version.id) for the month.
          - The draft pointer is moved to this newest id, so there is no "next" (redo) available.
          - We assert this by snapping the pointer to max(id) after insertion.
        """

        year, month = int(req.year), int(req.month)
        # _ensure_editable(year, month)  # Enable later to block edits on past periods
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

            # Snap the pointer to the newest draft id (clear REDO by construction).
            newest_id = (
                session.scalar(
                    select(func.max(ScheduleVersion.id)).where(
                        ScheduleVersion.year == year,
                        ScheduleVersion.month == month,
                        ScheduleVersion.kind == "draft",
                    )
                )
                or vid
            )
            vid = int(newest_id)

            ptr = _ensure_pointer(session, year, month)
            ptr.current_draft_version_id = vid
            session.add(ptr)

            _prune_drafts(session, year, month, keep_last=RETAIN_LAST_DRAFTS)

            diag = _compute_or_upsert_diagnostics(session, vid, payload)
            working = _read_working_read(session, year, month)

            drafts_total = _drafts_total(session, year, month)
            has_prev, has_next = _draft_neighbors(session, year, month, vid)

            session.commit()
            return ScheduleGenerateCreated(
                year=year,
                month=month,
                status=ScheduleStatus.draft,
                working=working,
                draft=_draft_view(
                    vid,
                    payload,
                    can_undo=has_prev,
                    can_redo=has_next,
                    count=drafts_total,
                ),
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

        Invariant (clear REDO semantics):
          - New checkpoint becomes the newest snapshot (max version.id) for the month.
          - The draft pointer is set to this newest id → no "next" (redo) exists.
          - We enforce this by snapping the pointer to max(id) after insertion.
        """

        # _ensure_editable(year, month)  # Enable later to block edits on past periods
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

            # Snap the pointer to the newest draft id (clear REDO by construction).
            newest_id = (
                session.scalar(
                    select(func.max(ScheduleVersion.id)).where(
                        ScheduleVersion.year == year,
                        ScheduleVersion.month == month,
                        ScheduleVersion.kind == "draft",
                    )
                )
                or vid
            )
            vid = int(newest_id)

            ptr = _ensure_pointer(session, year, month)
            ptr.current_draft_version_id = vid
            session.add(ptr)

            _prune_drafts(session, year, month, keep_last=RETAIN_LAST_DRAFTS)

            diag = _compute_or_upsert_diagnostics(session, vid, payload)

            drafts_total = _drafts_total(session, year, month)
            has_prev, has_next = _draft_neighbors(session, year, month, vid)

            session.commit()
            return ScheduleCheckpointCreated(
                year=year,
                month=month,
                draft=_draft_view(
                    vid,
                    payload,
                    can_undo=has_prev,
                    can_redo=has_next,
                    count=drafts_total,
                ),
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
        # _ensure_editable(year, month)  # Enable later to block edits on past periods

        with SessionLocal() as session:
            ptr = _ensure_pointer(session, year, month)

            # draft branch: pointer move, working overwrite
            if target == "draft":
                # Guard: there must be a current draft pointer to move from
                current = ptr.current_draft_version_id
                if current is None:
                    raise ValueError("cannot_undo" if direction == "prev" else "cannot_redo")

                # Find the neighbor draft version id based on direction
                if direction == "prev":
                    # Move pointer to the previous (older) draft version by id
                    prev_id = session.scalar(
                        select(func.max(ScheduleVersion.id)).where(
                            ScheduleVersion.year == year,
                            ScheduleVersion.month == month,
                            ScheduleVersion.kind == "draft",
                            ScheduleVersion.id < current,
                        )
                    )
                    if prev_id is None:
                        # No older draft exists → cannot undo
                        raise ValueError("cannot_undo")
                    new_id = int(prev_id)
                else:  # direction == "next"
                    # Move pointer to the next (newer) draft version by id
                    next_id = session.scalar(
                        select(func.min(ScheduleVersion.id)).where(
                            ScheduleVersion.year == year,
                            ScheduleVersion.month == month,
                            ScheduleVersion.kind == "draft",
                            ScheduleVersion.id > current,
                        )
                    )
                    if next_id is None:
                        # No newer draft exists → cannot redo
                        raise ValueError("cannot_redo")
                    new_id = int(next_id)

                # Update the draft pointer to the newly selected draft
                ptr.current_draft_version_id = new_id
                session.add(ptr)

                # Load the pointed draft snapshot and overwrite working payload with it
                ver = session.get(ScheduleVersion, new_id)
                if ver is None:
                    raise ValueError("not_found")

                _update_working(
                    session,
                    year,
                    month,
                    payload=ver.payload,
                    if_match_lock_version=None,  # working overwrite by pointer move is authoritative
                    updated_by_user_id=user_id,
                )

                # Recompute/refresh diagnostics for the selected draft version
                diag = _compute_or_upsert_diagnostics(session, new_id, ver.payload)

                # Read the updated working view for the response
                working = _read_working_read(session, year, month)

                # Compute flags and counters AFTER the pointer has moved
                drafts_total = _drafts_total(session, year, month)
                has_prev, has_next = _draft_neighbors(session, year, month, new_id)

                session.commit()
                return ScheduleRevertRead(
                    year=year,
                    month=month,
                    draft=_draft_view(new_id, ver.payload, can_undo=has_prev, can_redo=has_next, count=drafts_total),
                    working=working,
                    diagnostics=diag,
                )

            # published branch: pointer move only (no working overwrite)
            current = ptr.current_published_version_id
            if current is None:
                # No published head to move from
                raise ValueError("cannot_undo" if direction == "prev" else "cannot_redo")

            # Choose neighbor published version id based on direction
            if direction == "prev":
                new_id = session.scalar(
                    select(func.max(ScheduleVersion.id)).where(
                        ScheduleVersion.year == year,
                        ScheduleVersion.month == month,
                        ScheduleVersion.kind == "published",
                        ScheduleVersion.id < current,
                    )
                )
                if new_id is None:
                    # No older published exists → cannot undo
                    raise ValueError("cannot_undo")
            else:  # direction == "next"
                new_id = session.scalar(
                    select(func.min(ScheduleVersion.id)).where(
                        ScheduleVersion.year == year,
                        ScheduleVersion.month == month,
                        ScheduleVersion.kind == "published",
                        ScheduleVersion.id > current,
                    )
                )
                if new_id is None:
                    # No newer published exists → cannot redo
                    raise ValueError("cannot_redo")

            # Move the published pointer to the selected neighbor
            ptr.current_published_version_id = int(new_id)
            session.add(ptr)

            # Load the newly pointed published snapshot
            ver = session.get(ScheduleVersion, int(new_id))
            if ver is None:
                raise ValueError("not_found")

            # Compute flags and counters AFTER the pointer has moved
            publications_total = _published_total(session, year, month)
            has_prev, has_next = _published_neighbors(session, year, month, int(new_id))

            session.commit()
            return SchedulePublishedRevertRead(
                year=year,
                month=month,
                published=_published_view(
                    int(new_id),
                    ver.payload,
                    can_undo=has_prev,
                    can_redo=has_next,
                    count=publications_total,
                ),
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
        # _ensure_editable(year, month)  # Enable later to block edits on past periods
        with SessionLocal() as session:
            w = _get_or_init_working(session, year, month)
            payload = dict(w.payload or {"participant_doctor_ids": [], "assignments": [], "meta": {"labels": []}})
            meta = dict(payload.get("meta") or {"labels": []})

            # Evaluate hard-rule violations via dedicated helper
            hard_violations = _hard_rule_violations(payload)

            # Block publishing when non-forced and there are hard violations
            if not force and hard_violations:
                raise ValueError("publish_blocked_by_hard_rules")

            # Forced publish: verify accepted exceptions match detected violations, then append audit details
            if force:
                violation_codes = {v.get("code") for v in (hard_violations or []) if v.get("code")}
                if accepted_exceptions:
                    bad = [e.code for e in accepted_exceptions if e.code not in violation_codes]
                    if bad:
                        # The client attempted to accept exceptions that were not detected as hard violations
                        raise ValueError("invalid_accepted_exception")
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

            _prune_published(
                session, year, month, keep_last=RETAIN_LAST_PUBLISHED
            )  # no-op for now; retention policy to be defined

            audit = {"published_at": now_utc(), "published_by_user_id": user_id, "note": note or "Finalize"}

            publications_total = _published_total(session, year, month)
            has_prev, has_next = _published_neighbors(session, year, month, vid)

            session.commit()
            return SchedulePublishCreated(
                year=year,
                month=month,
                published=_published_view(
                    vid,
                    payload,
                    can_undo=has_prev,
                    can_redo=has_next,
                    count=publications_total,
                    audit=audit,
                ),
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

            publications_total = _published_total(session, year, month)
            has_prev, has_next = _published_neighbors(session, year, month, int(ver.id))

            return SchedulePublishedRead(
                year=year,
                month=month,
                org_timezone="Europe/Warsaw",
                period_status=PeriodStatus(get_period_status(year, month)),
                published=_published_view(
                    int(ver.id),
                    ver.payload,
                    can_undo=has_prev,
                    can_redo=has_next,
                    count=publications_total,  # lub max(... - 1, 0) — jeśli chcesz "poza headem"
                    audit={"published_at": ver.created_at},
                ),
            )
