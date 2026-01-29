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
- Domain errors are raised as ValueError with a short code.
- Some errors are raised as DomainError (subclass of ValueError) and can also carry:
    * .context (structured machine-readable payload for FE)
    * .detail  (optional human-friendly detail string)
  * "edit_conflict"  — optimistic concurrency violation on working PUT
  * "cannot_undo"    — there is no previous version to revert to
  * "cannot_redo"    — there is no next version to move forward to
  * "publish_blocked_by_hard_rules" — hard constraints prevent publishing without force
  * "not_found"      — requested entity/pointer/version does not exist
  * "generate_requires_ignore" — feasibility pre-check found blocking issues (see .context)
  * "generate_infeasible" — solver did not return SolverStatus.OK (see .context.solver_status)


TRANSACTIONAL POLICY (MVP)
--------------------------
- Each public method opens its own DB session and commits on success.
- Helper functions assume they run inside an active session/transaction.
- OCC: working updates accept if_match_lock_version and bump lock_version on write.

This module keeps routers thin. All domain rules live here.
"""

from __future__ import annotations

import calendar
from collections import Counter
from datetime import datetime
from functools import wraps
from typing import Any, Dict, List, Literal, Optional, Sequence, cast

from sqlalchemy import delete, func, select

# SQLAlchemy exception classes for translation.
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from backend.core import diagnostics as core_diagnostics
from backend.core import feasibility as core_feasibility
from backend.core import issues
from backend.core.types import DoctorInput, FeasibilityIssue, PreferencesInput, ProblemData, SolverStatus
from backend.db.session import SessionLocal
from backend.models.common_enums import (
    PeriodStatus,
    ScheduleStatus,
    ShiftType,
)
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
    HeadCommitmentResolution,
    MyAssignment,
    MyAssignmentsRead,
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
from backend.services import diagnostics_service
from backend.services.errors import DomainError
from backend.utils import ORG_TZ, days_in_month, get_period_status, normalize_assignments, normalize_meta, now_utc

# Retention policy (FIFO): tune here
# Change these to keep more/fewer historical snapshots.
RETAIN_LAST_DRAFTS = 5
RETAIN_LAST_PUBLISHED = 5

# ---- Error helpers (stable, deterministic payloads for FE) -------------------

ISSUES_SAMPLE_LIMIT = 30


def _detect_head_commitment_conflicts(problem: ProblemData) -> List[Dict[str, Any]]:
    """
    Detect "multiple heads want the same slot" conflicts based purely on preferences.

    Returns a list of conflicts:
      [{"day": 3, "shift_type": "onsite", "head_ids": [10, 12]}, ...]
    Deterministic order: by (day, shift_type).
    """
    # Collect head ids that are actually in this ProblemData + participant pool
    head_ids = sorted(
        [
            int(doc_id)
            for doc_id, doc in problem.doctors.items()
            if doc is not None and bool(doc.is_head) and int(doc_id) in set(problem.participant_doctor_ids)
        ]
    )

    wanted: Dict[tuple[int, ShiftType], List[int]] = {}

    for hid in head_ids:
        pref = problem.preferences.get(hid)
        if pref is None:
            continue

        for day in pref.preferred_onsite_days or []:
            wanted.setdefault((int(day), ShiftType.onsite), []).append(int(hid))

        for day in pref.preferred_oncall_days or []:
            wanted.setdefault((int(day), ShiftType.oncall), []).append(int(hid))

    conflicts: List[Dict[str, Any]] = []
    for (day, st), ids in wanted.items():
        uniq = sorted({int(x) for x in ids})
        if len(uniq) > 1:
            conflicts.append({"day": int(day), "shift_type": st.value, "head_ids": uniq})

    conflicts.sort(key=lambda x: (int(x["day"]), str(x["shift_type"])))
    return conflicts


def _apply_head_commitment_resolutions(problem: ProblemData, resolutions: List[HeadCommitmentResolution]) -> None:
    """
    Apply admin resolutions by editing ProblemData.preferences in-place.

    Rule:
    - For each (day, shift_type) resolution:
      * chosen_head keeps this day in preferred_*_days for that shift,
      * every other head has this day removed from their preferred_*_days for that shift.

    IMPORTANT:
    - This is NOT persisted to DB preferences. It's only for this generate request.
    """
    if not resolutions:
        return

    # Build a fast head set for validation
    head_ids = {
        int(doc_id)
        for doc_id, doc in problem.doctors.items()
        if doc is not None and bool(doc.is_head) and int(doc_id) in set(problem.participant_doctor_ids)
    }

    # Deduplicate by (day, shift_type): keep last (request validator also does this, but keep it defensive)
    last_by_slot: Dict[tuple[int, ShiftType], int] = {}
    for r in resolutions:
        slot = (int(r.day), ShiftType(r.shift_type))
        last_by_slot[slot] = int(r.chosen_head_id)

    for (day, st), chosen in last_by_slot.items():
        if int(chosen) not in head_ids:
            raise ValueError("invalid_head_commitment_resolution")

        for hid in sorted(head_ids):
            pref = problem.preferences.get(int(hid))
            if pref is None:
                continue

            if st == ShiftType.onsite:
                days = list(pref.preferred_onsite_days or [])
                if int(hid) == int(chosen):
                    # Ensure chosen has this day
                    if int(day) not in set(days):
                        days.append(int(day))
                else:
                    # Remove from others
                    days = [int(d) for d in days if int(d) != int(day)]
                pref.preferred_onsite_days = sorted({int(d) for d in days})

            else:  # ShiftType.oncall
                days = list(pref.preferred_oncall_days or [])
                if int(hid) == int(chosen):
                    if int(day) not in set(days):
                        days.append(int(day))
                else:
                    days = [int(d) for d in days if int(d) != int(day)]
                pref.preferred_oncall_days = sorted({int(d) for d in days})


def _build_issues_context(
    *,
    year: int,
    month: int,
    issues: Sequence[FeasibilityIssue],
    limit: int = ISSUES_SAMPLE_LIMIT,
) -> Dict[str, Any]:
    """
    Build a stable, deterministic context payload for FE when generation is blocked.

    We always return:
    - issues_sample: first N issues sorted by (day, code)
    - issues_total: total issues count
    - issues_truncated: whether we cut the list
    - issues_summary: counts per code (sorted by code)
    """

    # 1) Normalize issues to plain dicts (defensive: tolerate different shapes)
    normalized: List[Dict[str, Any]] = []
    for it in issues:
        # FeasibilityIssue is expected, but getattr keeps it defensive.
        day = int(getattr(it, "day", 0))
        code = str(getattr(it, "code", "unknown"))
        message = str(getattr(it, "message", code))

        normalized.append({"day": day, "code": code, "message": message})

    # 2) Deterministic order: by day, then code
    normalized.sort(key=lambda x: (int(x["day"]), str(x["code"])))

    # 3) Compute totals + truncation
    total = len(normalized)
    sample = normalized[: int(limit)]
    truncated = total > int(limit)

    # 4) Summary (counts per code) in deterministic order
    counts = Counter([str(x["code"]) for x in normalized])
    summary = [{"code": code, "count": int(counts[code])} for code in sorted(counts.keys())]

    return {
        "year": int(year),
        "month": int(month),
        "issues_sample": sample,
        "issues_total": int(total),
        "issues_truncated": bool(truncated),
        "issues_summary": summary,
    }


# ------------------------ SQLAlchemy error translation ------------------------
def _translate_sqla_errors(func):
    """
    Decorator that converts raw SQLAlchemy exceptions into our domain ValueError codes.

    Notes:
    - Not every IntegrityError is an OCC conflict.
      It can also be FK/NOT NULL/UNIQUE errors unrelated to optimistic concurrency.
    - We map to edit_conflict only when the error message strongly suggests OCC/lock_version issues.
    """

    @wraps(func)
    def _wrapped(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ValueError:
            # domain errors are already correct; let the router map them.
            raise
        except IntegrityError as ex:
            # Heuristic: treat as OCC conflict only if it mentions lock_version.
            # Otherwise, return a distinct code so we don't lie with "edit_conflict".
            msg = ""
            try:
                msg = str(getattr(ex, "orig", "") or str(ex)).lower()
            except Exception:
                msg = str(ex).lower()

            if "lock_version" in msg:
                raise ValueError("edit_conflict")

            raise ValueError("db_integrity_error")
        except SQLAlchemyError:
            # Any SQLAlchemyError here means "server/DB problem", NOT "not found".
            # We translate it to a stable domain code that router maps to HTTP 500.
            raise ValueError("db_error")

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
            inputs_snapshot=None,
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
        # Keep snapshot visible on working for deterministic publish/diagnostics later.
        inputs_snapshot=payload.get("inputs_snapshot"),
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
    older = session.scalar(
        select(func.max(ScheduleVersion.id)).where(
            ScheduleVersion.year == year,
            ScheduleVersion.month == month,
            ScheduleVersion.kind == "published",
            ScheduleVersion.id < current_id,
        )
    )
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

    if to_delete:
        session.execute(delete(ScheduleDiagnostics).where(ScheduleDiagnostics.version_id.in_(to_delete)))
        session.execute(delete(ScheduleVersion).where(ScheduleVersion.id.in_(to_delete)))

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

    Determinism rules (important):
    - If payload contains inputs_snapshot, diagnostics MUST be computed from that snapshot
      (doctor role/head/display_name + preference_version_id pointers captured at generation time).
    - This makes diagnostics stable for a given version_id, even if Doctor / PreferencePointer
      records change later in DB.

    Backward compatibility:
    - If inputs_snapshot is missing (older DB rows), we fall back to current DB-based loading.
    """

    # Prefer snapshot-driven deterministic inputs when available.
    if payload.get("inputs_snapshot") is not None:
        problem = diagnostics_service.build_problem_data_from_schedule_snapshot(
            db=session,
            year=int(year),
            month=int(month),
            schedule_payload=payload,
        )
    else:
        # Fallback for older versions without inputs_snapshot.
        req = ScheduleGenerateRequest(
            year=year,
            month=month,
            participant_doctor_ids=list(payload.get("participant_doctor_ids") or []),
            ignore_slots=[],
            head_commitment_resolutions=[],
        )
        problem = _build_problem_data_for_generate(session, req)

    quality_payload = core_diagnostics.compute_quality(problem=problem, payload=payload)

    row = session.execute(
        select(ScheduleDiagnostics).where(ScheduleDiagnostics.version_id == int(version_id))
    ).scalar_one_or_none()

    if row is None:
        row = ScheduleDiagnostics(version_id=int(version_id), quality=quality_payload)
        session.add(row)
    else:
        row.quality = quality_payload
        # IMPORTANT: ScheduleDiagnostics.computed_at has no onupdate=..., so refresh manually.
        row.computed_at = now_utc()

    session.flush()

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

    Current behavior (MVP):
    - Returns an empty list to keep publishing unblocked during development.
    """
    return []


def _normalize_snapshot_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a schedule snapshot payload before persisting as an immutable version.

    What it does:
    - Ensures participant_doctor_ids are integers (defensive cast).
    - Normalizes assignments (handles Enum values; sorts & dedupes by (day, shift_type, doctor_id)).
    - Normalizes meta (labels unique & sorted; exceptions must be a list).
    - Preserves inputs_snapshot if present.
    """
    payload = dict(raw or {})

    pids = payload.get("participant_doctor_ids") or []
    payload["participant_doctor_ids"] = [int(x) for x in pids]

    payload["assignments"] = normalize_assignments(cast(List[Dict[str, Any]], payload.get("assignments", []) or []))
    payload["meta"] = normalize_meta(cast(Dict[str, Any], payload.get("meta") or {"labels": []}))

    return payload


# --------------------------------- inputs snapshot helpers --------------------------------
def _doctor_display_name(d: Doctor) -> str:
    """
    Build a stable display name for snapshotting.
    """
    first = (d.first_name or "").strip()
    last = (d.last_name or "").strip()
    name = f"{first} {last}".strip()
    return name if name else f"Doctor {int(d.id)}"


def _build_inputs_snapshot(
    session: Session,
    *,
    year: int,
    month: int,
    participant_doctor_ids: set[int],
) -> Dict[str, Any]:
    """
    Create the frozen inputs snapshot for the schedule payload.

    IMPORTANT:
    - Snapshot uses PreferencePointer.current_version_id for {year, month},
      because that's what ProblemData loading uses at generation time.
    """
    ids = sorted({int(x) for x in (participant_doctor_ids or set())})
    if not ids:
        return {"doctors": {}, "preference_version_id_by_doctor": {}}

    db_doctors = session.scalars(select(Doctor).where(Doctor.id.in_(ids))).all()
    by_id: Dict[int, Doctor] = {int(d.id): d for d in db_doctors}

    doctors_snapshot: Dict[int, Dict[str, Any]] = {}
    for doctor_id in ids:
        d = by_id.get(int(doctor_id))
        if d is None:
            doctors_snapshot[int(doctor_id)] = {
                "role": "specialist",
                "is_head": False,
                "display_name": f"Doctor {int(doctor_id)}",
                "is_active_at_snapshot": False,
            }
            continue

        doctors_snapshot[int(doctor_id)] = {
            "role": d.role.value if hasattr(d.role, "value") else str(d.role),
            "is_head": bool(d.is_head),
            "display_name": _doctor_display_name(d),
            "is_active_at_snapshot": bool(d.is_active),
        }

    pref_map: Dict[int, Optional[int]] = {int(doctor_id): None for doctor_id in ids}

    ptr_rows = session.scalars(
        select(PreferencePointer).where(
            PreferencePointer.doctor_id.in_(ids),
            PreferencePointer.year == int(year),
            PreferencePointer.month == int(month),
        )
    ).all()

    for ptr in ptr_rows:
        did = int(ptr.doctor_id)
        pref_map[did] = int(ptr.current_version_id) if ptr.current_version_id is not None else None

    return {
        "doctors": doctors_snapshot,
        "preference_version_id_by_doctor": pref_map,
    }


# --------------------------------- DTO builders --------------------------------
def _build_problem_data_for_generate(session: Session, req: ScheduleGenerateRequest) -> ProblemData:
    """
    Build ProblemData for a generate request.

    This helper:
    - computes the list of days in the month,
    - loads active doctors from DB and maps them to DoctorInput,
    - intersects requested participant_doctor_ids with active doctors in DB,
    - builds PreferencesInput per participant doctor from PreferencePointer/PreferenceVersion (or defaults),
    - converts ignore_slots from the request to a set[(day, ShiftType)].

    IMPORTANT POLICY:
    - ignore_days does NOT exist anymore.
    - A whole day is ignored only by including BOTH slots in ignore_slots.
    """

    year = int(req.year)
    month = int(req.month)

    days_count = days_in_month(year, month)
    days = list(range(1, days_count + 1))

    weekdays = {day: calendar.weekday(year, month, day) for day in days}

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
        doctors[int(d.id)] = DoctorInput(
            id=int(d.id),
            role=d.role,
            is_head=bool(d.is_head),
            is_active=bool(d.is_active),
        )
        if d.is_active:
            active_ids.add(int(d.id))

    participant_doctor_ids: set[int] = requested_ids & active_ids

    preferences: Dict[int, PreferencesInput] = {}
    if participant_doctor_ids:
        ptr_rows = session.scalars(
            select(PreferencePointer).where(
                PreferencePointer.doctor_id.in_(participant_doctor_ids),
                PreferencePointer.year == year,
                PreferencePointer.month == month,
            )
        ).all()

        pointers_by_doctor: Dict[int, PreferencePointer] = {
            int(ptr.doctor_id): ptr for ptr in ptr_rows if ptr.current_version_id is not None
        }

        version_ids = {int(ptr.current_version_id) for ptr in ptr_rows if ptr.current_version_id is not None}

        versions_by_id: Dict[int, PreferenceVersion] = {}
        if version_ids:
            ver_rows = session.scalars(select(PreferenceVersion).where(PreferenceVersion.id.in_(version_ids))).all()
            versions_by_id = {int(ver.id): ver for ver in ver_rows}

        def _as_int_list(raw) -> List[int]:
            if not raw:
                return []
            if isinstance(raw, list):
                return [int(x) for x in raw]
            return []

        for doctor_id in participant_doctor_ids:
            payload: Dict[str, Any] = {}

            ptr = pointers_by_doctor.get(int(doctor_id))
            if ptr is not None and ptr.current_version_id is not None:
                ver = versions_by_id.get(int(ptr.current_version_id))
                if ver is not None and isinstance(ver.payload, dict):
                    payload = dict(ver.payload or {})

            preferences[doctor_id] = PreferencesInput(
                doctor_id=int(doctor_id),
                unavailable_onsite_days=_as_int_list(payload.get("unavailable_onsite_days")),
                unavailable_oncall_days=_as_int_list(payload.get("unavailable_oncall_days")),
                preferred_onsite_days=_as_int_list(payload.get("preferred_onsite_days")),
                preferred_oncall_days=_as_int_list(payload.get("preferred_oncall_days")),
                min_onsite_total=payload.get("min_onsite_total"),
                max_onsite_total=payload.get("max_onsite_total"),
                target_onsite_total=payload.get("target_onsite_total"),
                min_oncall_total=payload.get("min_oncall_total"),
                max_oncall_total=payload.get("max_oncall_total"),
                target_oncall_total=payload.get("target_oncall_total"),
                max_onsite_weekends=payload.get("max_onsite_weekends"),
                target_onsite_weekends=payload.get("target_onsite_weekends"),
                max_oncall_weekends=payload.get("max_oncall_weekends"),
                target_oncall_weekends=payload.get("target_oncall_weekends"),
                preferred_onsite_weekdays=_as_int_list(payload.get("preferred_onsite_weekdays")),
                preferred_oncall_weekdays=_as_int_list(payload.get("preferred_oncall_weekdays")),
                avoid_onsite_weekdays=_as_int_list(payload.get("avoid_onsite_weekdays")),
                avoid_oncall_weekdays=_as_int_list(payload.get("avoid_oncall_weekdays")),
                allow_weekend_consecutive_onsite_oncall=bool(
                    payload.get("allow_weekend_consecutive_onsite_oncall", False)
                ),
                preferred_partners=_as_int_list(payload.get("preferred_partners")),
                comments=payload.get("comments"),
            )

    # ignore_slots from request (validated by Pydantic)
    ignore_slots: set[tuple[int, ShiftType]] = set()
    for slot in req.ignore_slots or []:
        d = int(slot.day)
        if 1 <= d <= days_count:
            ignore_slots.add((d, slot.shift_type))

    problem = ProblemData(
        year=year,
        month=month,
        days=days,
        weekdays=weekdays,
        doctors=doctors,
        preferences=preferences,
        participant_doctor_ids=participant_doctor_ids,
        ignore_slots=ignore_slots,
    )

    try:
        _apply_head_commitment_resolutions(problem, list(req.head_commitment_resolutions or []))
    except ValueError:
        raise ValueError("invalid_head_commitment_resolution")

    return problem


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


def _payload_for_clean_quality(raw_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a COPY of payload suitable for 'clean' diagnostics:
    - keep everything the same,
    - but remove meta.exceptions so metrics/violations reflect the final schedule as-is.

    IMPORTANT:
    - We do NOT delete anything from the stored payload.
    - This is used only for computing quality.
    """
    payload = dict(raw_payload or {})
    meta = payload.get("meta") or {}
    if not isinstance(meta, dict):
        meta = {"labels": []}

    meta_clean = dict(meta)
    meta_clean["exceptions"] = []  # <-- key rule: compute on clean rules only
    payload["meta"] = meta_clean
    return payload


def _extract_hard_violations_from_quality(quality_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract hard (critical) violations from diagnostics payload.

    We treat findings with severity='critical' as publish-blocking violations.
    Returned list is deterministic (sorted by code).
    """
    details = quality_payload.get("details") or {}
    if not isinstance(details, dict):
        return []

    findings = details.get("findings") or []
    if not isinstance(findings, list):
        return []

    hard: List[Dict[str, Any]] = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        if str(f.get("severity")) != "critical":
            continue

        hard.append(
            {
                "code": str(f.get("code") or "unknown"),
                "message": str(f.get("message") or ""),
                "context": f.get("context") or {},
            }
        )

    hard.sort(key=lambda x: str(x.get("code", "")))
    return hard


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
        - get_my_assignments
    """

    # ------------------------------ Working -----------------------------------
    @_translate_sqla_errors
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
        with SessionLocal() as session:
            w = _get_or_init_working(session, year, month)
            current_payload = dict(w.payload or {})
            current_participants = list(current_payload.get("participant_doctor_ids", []))
            current_inputs_snapshot = current_payload.get("inputs_snapshot")

            norm_assignments: List[Dict[str, Any]] = normalize_assignments(
                [a if isinstance(a, dict) else a.model_dump(mode="json") for a in (assignments or [])]
            )
            norm_meta = normalize_meta(meta or {"labels": []})

            payload = {
                "participant_doctor_ids": current_participants,
                "assignments": norm_assignments,
                "meta": norm_meta,
            }
            if current_inputs_snapshot is not None:
                payload["inputs_snapshot"] = current_inputs_snapshot

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
        with SessionLocal() as session:
            year = int(req.year)
            month = int(req.month)

            # 1) Build ProblemData from DB + request (ignore_slots only)
            problem = _build_problem_data_for_generate(session, req)

            # 2) Gatekeeper: feasibility pre-check
            precheck_issues = core_feasibility.analyze_problem(problem)
            if precheck_issues:
                context = _build_issues_context(
                    year=year, month=month, issues=precheck_issues, limit=ISSUES_SAMPLE_LIMIT
                )
                raise DomainError("generate_requires_ignore", context=context)

            # 2b) Gatekeeper: head commitment conflicts must be resolved before solver
            conflicts = _detect_head_commitment_conflicts(problem)
            if conflicts:
                all_ids: set[int] = set()
                for c in conflicts:
                    for hid in c.get("head_ids", []):
                        all_ids.add(int(hid))

                name_by_id: Dict[int, str] = {}
                if all_ids:
                    db_heads = session.scalars(select(Doctor).where(Doctor.id.in_(sorted(all_ids)))).all()
                    for d in db_heads:
                        name_by_id[int(d.id)] = _doctor_display_name(d)

                conflicts_enriched: List[Dict[str, Any]] = []
                for c in conflicts:
                    head_ids = [int(x) for x in (c.get("head_ids") or [])]
                    conflicts_enriched.append(
                        {
                            "day": int(c["day"]),
                            "shift_type": str(c["shift_type"]),
                            "head_candidates": [
                                {"doctor_id": int(hid), "display_name": name_by_id.get(int(hid), f"Doctor {int(hid)}")}
                                for hid in head_ids
                            ],
                        }
                    )

                conflicts_enriched.sort(key=lambda x: (int(x["day"]), str(x["shift_type"])))

                context = {"year": int(year), "month": int(month), "head_commitment_conflicts": conflicts_enriched}
                raise DomainError("generate_requires_head_resolution", context=context)

            from backend.core import scheduler

            # 3) Call solver only when prechecks passed
            result = scheduler.generate_schedule(problem)
            solution = result.solution
            solver_assignments = result.assignments

            raw_status = getattr(solution, "status", None)
            solver_status_value = getattr(raw_status, "value", raw_status)

            if isinstance(solver_status_value, SolverStatus):
                solver_status_value = solver_status_value.value

            solver_status_value = str(solver_status_value)

            if solver_status_value != SolverStatus.OK.value:
                context = _build_issues_context(
                    year=year,
                    month=month,
                    issues=(solution.issues or []),
                    limit=ISSUES_SAMPLE_LIMIT,
                )
                context["solver_status"] = solver_status_value
                raise DomainError("generate_infeasible", context=context)

            def _assignment_to_dict(a: Any) -> Dict[str, Any]:
                if hasattr(a, "model_dump"):
                    return cast(Dict[str, Any], a.model_dump(mode="json"))
                if isinstance(a, dict):
                    return cast(Dict[str, Any], a)
                return {
                    "day": int(getattr(a, "day")),
                    "shift_type": getattr(getattr(a, "shift_type"), "value", getattr(a, "shift_type")),
                    "doctor_id": int(getattr(a, "doctor_id")),
                }

            # Derive ignored full days from ignore_slots (both slots ignored)
            ignored_days = sorted(
                {
                    int(d)
                    for d in problem.days
                    if (int(d), ShiftType.onsite) in problem.ignore_slots
                    and (int(d), ShiftType.oncall) in problem.ignore_slots
                }
            )

            exceptions: List[Dict[str, Any]] = []
            for d in ignored_days:
                exceptions.append({"code": issues.COVERAGE_IGNORED_DAY, "day": int(d)})

            for d, st in sorted(problem.ignore_slots, key=lambda x: (int(x[0]), str(x[1].value))):
                exceptions.append({"code": issues.COVERAGE_IGNORED_SLOT, "day": int(d), "shift_type": st.value})

            meta = {
                "labels": ["as_generated"],
                "exceptions": exceptions,
                "solver_status": solver_status_value,
            }

            inputs_snapshot = _build_inputs_snapshot(
                session,
                year=year,
                month=month,
                participant_doctor_ids=problem.participant_doctor_ids,
            )

            payload = _normalize_snapshot_payload(
                {
                    "participant_doctor_ids": sorted(problem.participant_doctor_ids),
                    "assignments": [_assignment_to_dict(a) for a in (solver_assignments or [])],
                    "inputs_snapshot": inputs_snapshot,
                    "meta": meta,
                }
            )

            _get_or_init_working(session, year, month)
            _update_working(
                session,
                year,
                month,
                payload=payload,
                if_match_lock_version=None,
                updated_by_user_id=user_id,
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
        """
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
        """
        with SessionLocal() as session:
            ptr = _ensure_pointer(session, year, month)

            if target == "draft":
                current = ptr.current_draft_version_id
                if current is None:
                    raise ValueError("cannot_undo" if direction == "prev" else "cannot_redo")

                if direction == "prev":
                    prev_id = session.scalar(
                        select(func.max(ScheduleVersion.id)).where(
                            ScheduleVersion.year == year,
                            ScheduleVersion.month == month,
                            ScheduleVersion.kind == "draft",
                            ScheduleVersion.id < current,
                        )
                    )
                    if prev_id is None:
                        raise ValueError("cannot_undo")
                    new_id = int(prev_id)
                else:
                    next_id = session.scalar(
                        select(func.min(ScheduleVersion.id)).where(
                            ScheduleVersion.year == year,
                            ScheduleVersion.month == month,
                            ScheduleVersion.kind == "draft",
                            ScheduleVersion.id > current,
                        )
                    )
                    if next_id is None:
                        raise ValueError("cannot_redo")
                    new_id = int(next_id)

                ptr.current_draft_version_id = new_id
                session.add(ptr)

                ver = session.get(ScheduleVersion, new_id)
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

                diag = _compute_or_upsert_diagnostics(
                    session, year=year, month=month, version_id=new_id, payload=cast(Dict[str, Any], ver.payload)
                )

                working = _read_working_read(session, year, month)

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

            current = ptr.current_published_version_id
            if current is None:
                raise ValueError("cannot_undo" if direction == "prev" else "cannot_redo")

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
                    raise ValueError("cannot_undo")
            else:
                new_id = session.scalar(
                    select(func.min(ScheduleVersion.id)).where(
                        ScheduleVersion.year == year,
                        ScheduleVersion.month == month,
                        ScheduleVersion.kind == "published",
                        ScheduleVersion.id > current,
                    )
                )
                if new_id is None:
                    raise ValueError("cannot_redo")

            ptr.current_published_version_id = int(new_id)
            session.add(ptr)

            ver = session.get(ScheduleVersion, int(new_id))
            if ver is None:
                raise ValueError("not_found")

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
        Publish current working.
        """
        with SessionLocal() as session:
            w = _get_or_init_working(session, year, month)
            payload = dict(w.payload or {"participant_doctor_ids": [], "assignments": [], "meta": {"labels": []}})

            payload = _normalize_snapshot_payload(payload)

            # Build ProblemData deterministically (snapshot if present)
            if payload.get("inputs_snapshot") is not None:
                problem = diagnostics_service.build_problem_data_from_schedule_snapshot(
                    db=session,
                    year=int(year),
                    month=int(month),
                    schedule_payload=payload,
                )
            else:
                req = ScheduleGenerateRequest(
                    year=year,
                    month=month,
                    participant_doctor_ids=list(payload.get("participant_doctor_ids") or []),
                    ignore_slots=[],
                    head_commitment_resolutions=[],
                )
                problem = _build_problem_data_for_generate(session, req)

            # Compute publish decision on CLEAN payload (ignore meta.exceptions)
            payload_clean = _payload_for_clean_quality(payload)
            quality_clean = core_diagnostics.compute_quality(problem=problem, payload=payload_clean)
            hard_violations = _extract_hard_violations_from_quality(quality_clean)

            # Keep "generation-time ignored" only for audit/information (NOT for scoring/violations)
            meta_raw = payload.get("meta") or {}
            generation_exceptions = []
            if isinstance(meta_raw, dict):
                generation_exceptions = list(meta_raw.get("exceptions") or [])

            meta = cast(Dict[str, Any], payload["meta"])

            hard_violations = _hard_rule_violations(payload)

            if not force and hard_violations:
                context = {
                    "year": int(year),
                    "month": int(month),
                    "hard_violations": hard_violations,
                    "diagnostics_summary": quality_clean.get("summary") or {},
                    "generation_exceptions": generation_exceptions,
                }
                raise DomainError("publish_blocked_by_hard_rules", context=context)

            if force:
                violation_codes = {v.get("code") for v in (hard_violations or []) if v.get("code")}

                if accepted_exceptions:
                    bad = [e.code for e in accepted_exceptions if e.code not in violation_codes]
                    if bad:
                        raise ValueError("invalid_accepted_exception")

                    # Append audit entries to meta.exceptions (keep existing generation exceptions too)
                    meta = cast(Dict[str, Any], payload.get("meta") or {"labels": []})
                    bad = [e.code for e in accepted_exceptions if e.code not in violation_codes]
                    if bad:
                        raise ValueError("invalid_accepted_exception")

                    # 1) Normalize meta FIRST (labels, base shape etc.)
                    meta_norm = normalize_meta(meta)

                    # 2) Append audit entries AFTER normalization so they are not dropped
                    ex_list = list(meta_norm.get("exceptions", []))

                    for e in accepted_exceptions:
                        ex_list.append(
                            {
                                "code": e.code,
                                "justification": e.justification,
                                "accepted_by_user_id": user_id,
                                "accepted_at": now_utc().isoformat(),
                            }
                        )

                        meta_norm["exceptions"] = ex_list
                        payload["meta"] = meta_norm

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

            _prune_published(session, year, month, keep_last=RETAIN_LAST_PUBLISHED)

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
                    count=publications_total,
                    audit={"published_at": ver.created_at},
                ),
            )

    # -------------------------- Doctor: my assignments --------------------------
    @_translate_sqla_errors
    def get_my_assignments(self, year: int, month: int, *, doctor_id: int) -> MyAssignmentsRead:
        """
        Return assignments for a single doctor from the current PUBLISHED schedule.
        """
        with SessionLocal() as session:
            ptr = session.get(SchedulePointer, {"year": year, "month": month})
            if ptr is None or ptr.current_published_version_id is None:
                raise ValueError("not_found")

            ver = session.get(ScheduleVersion, int(ptr.current_published_version_id))
            if ver is None:
                raise ValueError("not_found")

            payload_obj = SchedulePayload.model_validate(ver.payload)

            mine: List[MyAssignment] = []
            for a in payload_obj.assignments or []:
                if int(a.doctor_id) == int(doctor_id):
                    mine.append(MyAssignment(day=int(a.day), shift_type=a.shift_type))

            mine = sorted(mine, key=lambda x: (int(x.day), str(x.shift_type.value)))

            return MyAssignmentsRead(
                doctor_id=int(doctor_id),
                year=year,
                month=month,
                assignments=mine,
            )

    @_translate_sqla_errors
    def get_diagnostics(
        self, year: int, month: int, *, target: Literal["working", "draft", "published"]
    ) -> DiagnosticsRead:
        """
        Return diagnostics for the selected stream of {year, month}.
        """
        with SessionLocal() as db:
            if target == "working":
                w = db.get(ScheduleWorking, {"year": year, "month": month})
                if w is None:
                    raise ValueError("not_found")

                payload = cast(Dict[str, Any], w.payload or {})

                if payload.get("inputs_snapshot") is not None:
                    problem = diagnostics_service.build_problem_data_from_schedule_snapshot(
                        db=db,
                        year=int(year),
                        month=int(month),
                        schedule_payload=payload,
                    )
                else:
                    req = ScheduleGenerateRequest(
                        year=year,
                        month=month,
                        participant_doctor_ids=list(payload.get("participant_doctor_ids") or []),
                        ignore_slots=[],
                        head_commitment_resolutions=[],
                    )
                    problem = _build_problem_data_for_generate(db, req)

                payload_clean = _payload_for_clean_quality(payload)
                quality_payload = core_diagnostics.compute_quality(problem=problem, payload=payload_clean)

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
        """
        with SessionLocal() as session:
            period_status = PeriodStatus(get_period_status(year, month))

            working = _read_working_read(session, year, month)

            ptr = session.get(SchedulePointer, {"year": year, "month": month})
            has_draft_ptr = bool(ptr and ptr.current_draft_version_id is not None)
            has_pub_ptr = bool(ptr and ptr.current_published_version_id is not None)

            default_mode = "published" if (not has_draft_ptr and has_pub_ptr) else "draft"
            toggle_available = bool(has_draft_ptr and has_pub_ptr)
            view_hint = _ViewHint(default_mode=default_mode, toggle_available=toggle_available)

            if (not working.exists) and not has_draft_ptr and not has_pub_ptr:
                return SchedulesPeriodViewRead(
                    year=year,
                    month=month,
                    org_timezone=ORG_TZ,
                    period_status=period_status,
                    view=view_hint,
                    working=working,
                    draft=ScheduleDraftView(),
                    published=SchedulePublishedView(),
                    diagnostics=None,
                )

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

                diagnostics = _compute_or_upsert_diagnostics(
                    session, year=year, month=month, version_id=did, payload=cast(Dict[str, Any], ver.payload)
                )

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
                diagnostics=diagnostics,
            )
