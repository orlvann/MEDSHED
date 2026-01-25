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

import calendar
from datetime import datetime
from functools import wraps
from typing import Any, Dict, List, Literal, Optional, cast

from sqlalchemy import delete, func, select

# SQLAlchemy exception classes for translation.
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from backend.core import diagnostics as core_diagnostics
from backend.core.types import DoctorInput, PreferencesInput, ProblemData
from backend.db.session import SessionLocal
from backend.models.common_enums import PeriodStatus, ScheduleStatus, ShiftType
from backend.models.orm.doctor import Doctor
from backend.models.orm.preference import PreferencePointer, PreferenceVersion
from backend.models.orm.schedule import (
    ScheduleDiagnostics,
    SchedulePointer,
    ScheduleVersion,
    ScheduleWorking,
)
from backend.models.schemas.diagnostics import DiagnosticsRead, DiagnosticsSummary
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
    SchedulesPeriodViewRead,
    ScheduleWorkingAck,
    ScheduleWorkingRead,
    _ViewHint,
)
from backend.utils import ORG_TZ, days_in_month, get_period_status, normalize_assignments, normalize_meta, now_utc

# Retention policy (FIFO): tune here
# Change these to keep more/fewer historical snapshots.
RETAIN_LAST_DRAFTS = 5
RETAIN_LAST_PUBLISHED = 5


def _translate_sqla_errors(func):
    """
    Decorator that converts raw SQLAlchemy exceptions into our domain ValueError codes.
    Rules:
      - IntegrityError -> ValueError("edit_conflict")
      - Any other SQLAlchemyError -> ValueError("not_found")
      - Domain ValueError passes through unchanged (we don't touch it).
    """

    @wraps(func)
    def _wrapped(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ValueError:
            # domain errors are already correct; let the router map them.
            raise
        except IntegrityError:
            # treat integrity/unique/OCC-like DB issues as edit conflicts.
            raise ValueError("edit_conflict")
        except SQLAlchemyError:
            # safe fallback for DB-layer problems that should not leak details.
            raise ValueError("not_found")

    return _wrapped


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


def _compute_or_upsert_diagnostics(
    session: Session,
    *,
    year: int,
    month: int,
    version_id: int,
    payload: Dict[str, Any],
) -> DiagnosticsRead:
    """
    Compute and upsert diagnostics for a given schedule version.

    Now (real MVP):
    - build ProblemData for participants from payload
    - compute analytics in backend/core/diagnostics.py
    - store JSON {summary, details} in ScheduleDiagnostics.quality
    """

    # Build ProblemData using the same logic as "generate" (but no ignores here).
    # We reuse your helper by creating a minimal request-like object.
    req = ScheduleGenerateRequest(
        year=year,
        month=month,
        participant_doctor_ids=list(payload.get("participant_doctor_ids") or []),
        ignore_days=[],
        ignore_slots=[],
    )
    problem = _build_problem_data_for_generate(session, req)

    # Compute quality (pure core logic)
    quality_payload = core_diagnostics.compute_quality(problem=problem, payload=payload)

    # Upsert diagnostics row
    row = session.execute(
        select(ScheduleDiagnostics).where(ScheduleDiagnostics.version_id == int(version_id))
    ).scalar_one_or_none()

    if row is None:
        row = ScheduleDiagnostics(version_id=int(version_id), quality=quality_payload)
        session.add(row)
    else:
        row.quality = quality_payload

    session.flush()

    # Build DTO response (Pydantic model types, not raw dicts)
    summary_dict = quality_payload.get("summary") or {}
    summary_obj = DiagnosticsSummary.model_validate(summary_dict)

    return DiagnosticsRead(
        version_id=str(version_id),
        computed_at=row.computed_at,
        summary=summary_obj,
        details=quality_payload.get("details"),
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


def _normalize_snapshot_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a schedule snapshot payload before persisting as an immutable version.

    What it does:
    - Ensures participant_doctor_ids are integers (defensive cast).
    - Normalizes assignments (handles Enum values; sorts & dedupes by (day, shift_type, doctor_id)).
    - Normalizes meta (labels unique & sorted; exceptions must be a list).

    Why:
    - Keep all versions deterministic and comparable (no false diffs due to order/dup).
    - Make snapshots tolerant to upstream sources that might pass Enum objects.

    Note:
    - This helper is used for *immutable* snapshots (draft/published).
      Working (autosave) is normalized in `save_working` separately.
    """
    payload = dict(raw or {})

    # Defensive cast of participants to ints
    pids = payload.get("participant_doctor_ids") or []
    payload["participant_doctor_ids"] = [int(x) for x in pids]

    # Assignments: coerce possible Enums to their .value and normalize
    payload["assignments"] = normalize_assignments(cast(List[Dict[str, Any]], payload.get("assignments", []) or []))

    # Meta: ensure labels unique & sorted; exceptions list
    payload["meta"] = normalize_meta(cast(Dict[str, Any], payload.get("meta") or {"labels": []}))

    return payload


# --------------------------------- DTO builders --------------------------------
def _build_problem_data_for_generate(session: Session, req: ScheduleGenerateRequest) -> ProblemData:
    """
    Build ProblemData for a generate request.

    ```
    This helper:
    - computes the list of days in the month,
    - loads active doctors from DB and maps them to DoctorInput,
    - intersects requested participant_doctor_ids with active doctors in DB,
    - builds PreferencesInput per participant doctor from PreferencePointer/PreferenceVersion (or defaults),
    - converts ignore_days and ignore_slots from the request to sets.
    """

    # Parse year and month as plain integers
    year = int(req.year)
    month = int(req.month)

    # 1) Days of the month: 1..N using days_in_month helper
    days_count = days_in_month(year, month)
    days = list(range(1, days_count + 1))

    # Map each calendar day to its weekday (0=Mon .. 6=Sun)
    weekdays = {day: calendar.weekday(year, month, day) for day in days}

    # 2) Load doctors from DB (requested ids, filtered to is_active=True)
    requested_ids = {int(did) for did in (req.participant_doctor_ids or [])}
    doctors: Dict[int, DoctorInput] = {}

    if requested_ids:
        db_doctors = session.scalars(
            select(Doctor).where(
                Doctor.id.in_(requested_ids),
                Doctor.is_active.is_(True),
            )
        ).all()
    else:
        db_doctors = []

    active_ids: set[int] = set()

    for d in db_doctors:
        # Build minimal DoctorInput used by the solver
        doctors[int(d.id)] = DoctorInput(
            id=int(d.id),
            role=d.role,
            is_head=bool(d.is_head),
            is_active=bool(d.is_active),
        )
        if d.is_active:
            active_ids.add(int(d.id))

    # 3) Participant ids = intersection of requested ids and active doctors from DB
    participant_doctor_ids: set[int] = requested_ids & active_ids

    # 4) Build preferences for each participant doctor
    #    We use PreferencePointer + PreferenceVersion to read the latest submitted version.
    #    If anything is missing, we fall back to empty/default PreferencesInput.
    preferences: Dict[int, PreferencesInput] = {}
    if participant_doctor_ids:
        # Load all pointers for this period and participant doctors in one query
        ptr_rows = session.scalars(
            select(PreferencePointer).where(
                PreferencePointer.doctor_id.in_(participant_doctor_ids),
                PreferencePointer.year == year,
                PreferencePointer.month == month,
            )
        ).all()

        # Map doctor_id -> pointer row (only when a version id is present)
        pointers_by_doctor: Dict[int, PreferencePointer] = {
            int(ptr.doctor_id): ptr for ptr in ptr_rows if ptr.current_version_id is not None
        }

        # Collect all version ids that we need to load
        version_ids = {int(ptr.current_version_id) for ptr in ptr_rows if ptr.current_version_id is not None}

        versions_by_id: Dict[int, PreferenceVersion] = {}
        if version_ids:
            # Load all referenced versions in one query
            ver_rows = session.scalars(select(PreferenceVersion).where(PreferenceVersion.id.in_(version_ids))).all()
            versions_by_id = {int(ver.id): ver for ver in ver_rows}

        # Helper to safely convert JSON list fields to a plain list of ints
        def _as_int_list(raw) -> List[int]:
            # If value is missing or null, return an empty list
            if not raw:
                return []
            if isinstance(raw, list):
                # Cast values to int defensively
                return [int(x) for x in raw]
            return []

        # Build PreferencesInput for each participant doctor
        for doctor_id in participant_doctor_ids:
            payload: Dict[str, Any] = {}

            ptr = pointers_by_doctor.get(int(doctor_id))
            if ptr is not None and ptr.current_version_id is not None:
                ver = versions_by_id.get(int(ptr.current_version_id))
                if ver is not None and isinstance(ver.payload, dict):
                    # Copy payload to avoid mutating ORM-attached dict
                    payload = dict(ver.payload or {})

            # Map JSON payload to PreferencesInput; defaults are used when keys are missing
            # Map JSON payload to PreferencesInput; defaults are used when keys are missing.
            #
            # Note: Optional[int] fields can be missing -> None (that's OK).
            # If later you want stricter typing, you can add a helper like _as_int_or_none().
            preferences[doctor_id] = PreferencesInput(
                doctor_id=int(doctor_id),
                # Day-level preferences: 1..31
                unavailable_onsite_days=_as_int_list(payload.get("unavailable_onsite_days")),
                unavailable_oncall_days=_as_int_list(payload.get("unavailable_oncall_days")),
                preferred_onsite_days=_as_int_list(payload.get("preferred_onsite_days")),
                preferred_oncall_days=_as_int_list(payload.get("preferred_oncall_days")),
                # Monthly totals (soft caps and targets
                min_onsite_total=payload.get("min_onsite_total"),
                max_onsite_total=payload.get("max_onsite_total"),
                target_onsite_total=payload.get("target_onsite_total"),
                min_oncall_total=payload.get("min_oncall_total"),
                max_oncall_total=payload.get("max_oncall_total"),
                target_oncall_total=payload.get("target_oncall_total"),
                # Weekend-specific caps and targets
                max_onsite_weekends=payload.get("max_onsite_weekends"),
                target_onsite_weekends=payload.get("target_onsite_weekends"),
                max_oncall_weekends=payload.get("max_oncall_weekends"),
                target_oncall_weekends=payload.get("target_oncall_weekends"),
                # Weekly patterns (0=Mon .. 6=Sun)
                preferred_onsite_weekdays=_as_int_list(payload.get("preferred_onsite_weekdays")),
                preferred_oncall_weekdays=_as_int_list(payload.get("preferred_oncall_weekdays")),
                avoid_onsite_weekdays=_as_int_list(payload.get("avoid_onsite_weekdays")),
                avoid_oncall_weekdays=_as_int_list(payload.get("avoid_oncall_weekdays")),
                # Flags and relationships
                allow_weekend_consecutive_onsite_oncall=bool(
                    payload.get("allow_weekend_consecutive_onsite_oncall", False)
                ),
                preferred_partners=_as_int_list(payload.get("preferred_partners")),
                comments=payload.get("comments"),
            )

    # When there are no participants, 'preferences' stays empty dict (solver sees no doctors)

    # 5) Ignored days and slots from the request
    # Keep only days that actually exist in this month (1..days_count).
    raw_ignore_days: set[int] = {int(day) for day in (req.ignore_days or [])}
    ignore_days: set[int] = {d for d in raw_ignore_days if 1 <= d <= days_count}

    ignore_slots: set[tuple[int, ShiftType]] = set()
    for slot in req.ignore_slots or []:
        # slot is IgnoreSlot DTO with day and ShiftType enum
        d = int(slot.day)
        if 1 <= d <= days_count:
            ignore_slots.add((d, slot.shift_type))

    # 6) Build and return ProblemData for the solver
    return ProblemData(
        year=year,
        month=month,
        days=days,
        weekdays=weekdays,
        doctors=doctors,
        preferences=preferences,
        participant_doctor_ids=participant_doctor_ids,
        ignore_days=ignore_days,
        ignore_slots=ignore_slots,
    )


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
    @_translate_sqla_errors
    # Decorator: wraps this method and translates raw SQLAlchemy exceptions into our domain ValueError codes
    # (e.g., "edit_conflict", "not_found"), so DB internals don’t leak past the service layer.
    def get_working(self, year: int, month: int) -> ScheduleWorkingRead:
        """
        Read the current working buffer or return a skeleton if it doesn't exist.
        """
        with SessionLocal() as session:
            return _read_working_read(session, year, month)

    @_translate_sqla_errors
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

        Semantics (IMPORTANT):
            - PUT /working MUST NOT change 'participant_doctor_ids'.
            - 'participant_doctor_ids' are preserved from the CURRENT working row.
            - The only supported way to change 'participant_doctor_ids' is via 'generate'
            (snapshot of the participants pool).

        Normalization (enforced here):
            - Assignments are normalized (sort & dedupe by (day, shift_type, doctor_id)).
            - Meta is normalized via 'normalize_meta' (labels unique & sorted; exceptions list).
            - Deterministic shape avoids "false diffs" and keeps snapshots stable.

        Returns:
            - ScheduleWorkingAck with updated_at and new lock_version.

        Raises:
            - ValueError("edit_conflict") when OCC precondition fails.
        """
        # _ensure_editable(year, month)  # Enable later to block edits on past periods

        with SessionLocal() as session:
            # Load current working to preserve participant_doctor_ids
            w = _get_or_init_working(session, year, month)
            current_payload = dict(w.payload or {})
            current_participants = list(current_payload.get("participant_doctor_ids", []))

            # Normalize inputs
            norm_assignments: List[Dict[str, Any]] = normalize_assignments(
                [a if isinstance(a, dict) else a.model_dump(mode="json") for a in (assignments or [])]
            )

            norm_meta = normalize_meta(meta or {"labels": []})

            # Build the new working snapshot WITHOUT touching participant_doctor_ids
            payload = {
                "participant_doctor_ids": current_participants,
                "assignments": norm_assignments,
                "meta": norm_meta,
            }

            # OCC write (will raise ValueError("edit_conflict") on mismatch)
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
    @_translate_sqla_errors
    def generate(self, req: ScheduleGenerateRequest, *, user_id: Optional[int]) -> ScheduleGenerateCreated:
        """
        Generate (MVP): build ProblemData, call the solver, seed working and create first draft version.
            Behavior:
            - Builds ProblemData from DB and request (participants, preferences stub, ignore_*).
            - Calls the core scheduler to get assignments (may be empty list in MVP).
            - Seeds/overwrites working with solver assignments and meta.
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
            # Build core ProblemData from DB and request
            problem = _build_problem_data_for_generate(session, req)

            # Lazy import to avoid potential circular imports at module import time
            from backend.core import scheduler

            # Call solver to generate schedule result (solution + assignments)
            result = scheduler.generate_schedule(problem)

            solution = result.solution
            assignments = result.assignments

            # Normalize snapshot payload: use participants from ProblemData + solver assignments
            meta = {
                "labels": ["as_generated"],
                "exceptions": [],
                # Store solver status as plain string for JSON/meta
                "solver_status": solution.status.value,
            }

            # Add admin-requested ignores as "exceptions" so they are visible in meta (stable field).
            # This answers why some days are missing in a schedule generated by the solver
            for d in sorted(problem.ignore_days):
                meta["exceptions"].append(
                    {
                        "code": "ignored_day",
                        "day": d,
                        "justification": "Skipped by admin request (ignore_days).",
                    }
                )

            for d, st in sorted(problem.ignore_slots, key=lambda x: (x[0], x[1].value)):
                meta["exceptions"].append(
                    {
                        "code": "ignored_slot",
                        "day": d,
                        "shift_type": st.value,
                        "justification": "Skipped by admin request (ignore_slots).",
                    }
                )

            # Keep real feasibility issues ONLY when solver reported them (optional).
            if solution.issues:
                for i in solution.issues:
                    meta["exceptions"].append(
                        {
                            "code": i.code,
                            "day": i.day,
                            "justification": i.message,
                        }
                    )

            payload = _normalize_snapshot_payload(
                {
                    "participant_doctor_ids": sorted(problem.participant_doctor_ids),
                    "assignments": [a.model_dump(mode="json") for a in assignments],
                    "meta": meta,
                }
            )

            # Ensure working row exists and overwrite it with the new snapshot
            _get_or_init_working(session, year, month)
            _update_working(
                session, year, month, payload=payload, if_match_lock_version=None, updated_by_user_id=user_id
            )

            # Create an immutable draft version based on the same payload
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

            diag = _compute_or_upsert_diagnostics(session, year=year, month=month, version_id=vid, payload=payload)
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
    @_translate_sqla_errors
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

            payload = _normalize_snapshot_payload(payload)

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

            diag = _compute_or_upsert_diagnostics(session, year=year, month=month, version_id=vid, payload=payload)

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
    @_translate_sqla_errors
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
                diag = _compute_or_upsert_diagnostics(
                    session, year=year, month=month, version_id=new_id, payload=cast(Dict[str, Any], ver.payload)
                )

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
    @_translate_sqla_errors
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
            # normalize both assignments and meta
            # Normalize entire snapshot in one place (handles enums, sorting, dedup, labels)
            payload = _normalize_snapshot_payload(payload)
            meta = cast(Dict[str, Any], payload["meta"])  # keep a typed alias for edits below

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
                    payload["meta"] = normalize_meta(meta)

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

            _compute_or_upsert_diagnostics(session, year=year, month=month, version_id=vid, payload=payload)

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
    @_translate_sqla_errors
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

    @_translate_sqla_errors
    def get_diagnostics(
        self, year: int, month: int, *, target: Literal["working", "draft", "published"]
    ) -> DiagnosticsRead:
        """
        Return diagnostics for the selected stream of {year, month}.

        Streams:
        - working   -> live autosave buffer (NOT pointer-based, NOT cached in ScheduleDiagnostics)
        - draft     -> pointer-based immutable version (cached/upserted)
        - published -> pointer-based immutable version (cached/upserted)
        """
        with SessionLocal() as db:
            # ----------------------------- target=working -----------------------------
            if target == "working":
                w = db.get(ScheduleWorking, {"year": year, "month": month})
                if w is None:
                    raise ValueError("not_found")

                payload = cast(Dict[str, Any], w.payload or {})

                req = ScheduleGenerateRequest(
                    year=year,
                    month=month,
                    participant_doctor_ids=list(payload.get("participant_doctor_ids") or []),
                    ignore_days=[],
                    ignore_slots=[],
                )
                problem = _build_problem_data_for_generate(db, req)

                quality_payload = core_diagnostics.compute_quality(problem=problem, payload=payload)

                summary_dict = quality_payload.get("summary") or {}
                summary_obj = DiagnosticsSummary.model_validate(summary_dict)

                details = quality_payload.get("details") or {}
                if not isinstance(details, dict):
                    details = {}
                details["working_lock_version"] = w.lock_version

                return DiagnosticsRead(
                    version_id="working",
                    computed_at=now_utc(),
                    summary=summary_obj,
                    details=details,
                )

            # -------------------------- target=draft/published -------------------------
            ptr = db.get(SchedulePointer, {"year": year, "month": month})
            if not ptr:
                raise ValueError("not_found")

            vid = ptr.current_draft_version_id if target == "draft" else ptr.current_published_version_id
            if vid is None:
                raise ValueError("not_found")

            ver = db.get(ScheduleVersion, int(vid))
            if ver is None:
                raise ValueError("not_found")

            diag = _compute_or_upsert_diagnostics(
                db,
                year=year,
                month=month,
                version_id=int(vid),
                payload=cast(Dict[str, Any], ver.payload),
            )
            db.commit()
            return diag

    @_translate_sqla_errors
    def get_period_view(self, year: int, month: int) -> SchedulesPeriodViewRead:
        """
        Build a unified Period View for Admin tab.

        Policy:
        - Skeleton when nothing exists.
        - Always include 'working' if present.
        - Include DRAFT view only when a draft pointer exists (no synthetic draft here).
        - Include PUBLISHED view only when a published pointer exists.
        - Include diagnostics only when we have a real draft version_id (pointer-based).
        - Toggle logic:
          * default_mode="published" if draft pointer is missing but published exists; else "draft".
          * toggle_available=True only if both draft and published pointers exist.
        """
        with SessionLocal() as session:
            period_status = PeriodStatus(get_period_status(year, month))

            # Working (explicit read; may return skeleton with exists=False)
            working = _read_working_read(session, year, month)

            # Pointers (may be None)
            ptr = session.get(SchedulePointer, {"year": year, "month": month})
            has_draft_ptr = bool(ptr and ptr.current_draft_version_id is not None)
            has_pub_ptr = bool(ptr and ptr.current_published_version_id is not None)

            # View hint (toggle + default mode) computed from pointers:
            # - default to "published" only when draft pointer is missing and published exists
            # - toggle only when both streams exist
            default_mode = "published" if (not has_draft_ptr and has_pub_ptr) else "draft"
            toggle_available = bool(has_draft_ptr and has_pub_ptr)
            view_hint = _ViewHint(default_mode=default_mode, toggle_available=toggle_available)

            # Early skeleton: no working and no pointers at all
            if (not working.exists) and not has_draft_ptr and not has_pub_ptr:
                return SchedulesPeriodViewRead(
                    year=year,
                    month=month,
                    org_timezone=ORG_TZ,
                    period_status=period_status,
                    view=view_hint,
                    working=working,
                    draft=ScheduleDraftView(),  # empty
                    published=SchedulePublishedView(),  # empty
                    diagnostics=None,
                )

            # Build DRAFT (only if a real draft pointer exists)
            draft_view = ScheduleDraftView()
            diagnostics: DiagnosticsRead | None = None
            if has_draft_ptr:
                did = int(ptr.current_draft_version_id)  # type: ignore[union-attr]
                ver = session.get(ScheduleVersion, did)
                if ver is None:
                    raise ValueError("not_found")

                drafts_total = _drafts_total(session, year, month)
                has_prev, has_next = _draft_neighbors(session, year, month, did)

                draft_view = _draft_view(
                    did,
                    ver.payload,
                    can_undo=has_prev,
                    can_redo=has_next,
                    count=drafts_total,
                )

                # Diagnostics only when draft pointer exists (period view shows draft KPIs)
                diagnostics = _compute_or_upsert_diagnostics(
                    session, year=year, month=month, version_id=did, payload=cast(Dict[str, Any], ver.payload)
                )

            # Build PUBLISHED (only if published pointer exists)
            published_view = SchedulePublishedView()
            if has_pub_ptr:
                pid = int(ptr.current_published_version_id)  # type: ignore[union-attr]
                verp = session.get(ScheduleVersion, pid)
                if verp is None:
                    raise ValueError("not_found")

                pubs_total = _published_total(session, year, month)
                has_prev_p, has_next_p = _published_neighbors(session, year, month, pid)

                published_view = _published_view(
                    pid,
                    verp.payload,
                    can_undo=has_prev_p,
                    can_redo=has_next_p,
                    count=pubs_total,
                    audit={"published_at": verp.created_at},
                )

            return SchedulesPeriodViewRead(
                year=year,
                month=month,
                org_timezone=ORG_TZ,
                period_status=period_status,
                view=view_hint,
                working=working,
                draft=draft_view,
                published=published_view,
                diagnostics=diagnostics,  # None when no draft pointer
            )
