# backend/services/scheduling_service.py
"""
Scheduling Service — orchestrates schedule generation & lifecycle.

Coordinates:
- Preparing solver input (load doctors, preferences, constraints).
- Running the scheduler from core/ to generate schedules.
- Managing drafts, manual edits, publish/unpublish flows.
- Saving results and assignments to the database.

Responsibilities:
- End-to-end workflow orchestration (multi-step process).
- Keep 'working draft' separate from immutable stored versions.
- Maintain checkpoints for undo/redo within the draft lifecycle.
- Enforce publishing rules (at most one published per {year, month}).

Depends on:
- ORM: Schedule, Assignment (and related tables)
- core/ (scheduler.py, heuristics/, constraints/)
- diagnostics_service for post-run metrics (cache per version)

Notes:
- This module keeps routers THIN. Business rules live here.
- For MVP we expose minimal in-memory storage for "working" so the UI can run.
- All places for ORM are marked with explicit TODO steps.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Tuple

# Single source of truth for time & normalization utilities.
# utils/__init__.py re-exports:
#   - now_utc (from utils/timez.py)
#   - normalize_assignments (from utils/normalization.py)
from backend.utils import normalize_assignments, now_utc
from backend.utils.timez import is_period_closed

# ==============================================================================
# MVP in-memory store (only for demo/stub) — remove when ORM is ready
# Key: (year, month) → dict with working state incl. lock_version
# ==============================================================================

_MEMORY_WORKING: dict[tuple[int, int], Dict[str, Any]] = {}


def _ensure_seed(year: int, month: int) -> Dict[str, Any]:
    """
    Create a predictable stub 'working' if not present. (MVP only)

    Shape matches ScheduleWorkingRead fields the router expects.
    """
    key = (year, month)
    if key not in _MEMORY_WORKING:
        _MEMORY_WORKING[key] = {
            "participant_doctor_ids": [1, 2, 5, 7],
            "assignments": [],
            "meta": {"labels": ["as_generated"]},
            "updated_at": now_utc(),
            "lock_version": 1,  # hard OCC integer starts at 1
        }
    return _MEMORY_WORKING[key]


def _ensure_editable_or_raise(year: int, month: int) -> None:
    """
    Defensive time guard for ALL mutating flows.

    If the period is closed in org TZ, we block edits at the service layer.
    Router may also check it, but we enforce defense-in-depth here.

    Raises:
        ValueError("period_closed") — routers convert to HTTP 403 with code=period_closed.
    """
    if is_period_closed(year, month):
        raise ValueError("period_closed")


# ==============================================================================
# READ helpers (used by routers)
# ==============================================================================


def get_working(year: int, month: int) -> Optional[Dict[str, Any]]:
    """
    Return the current working draft for the period or None if missing.

    Post-ORM:
      - SELECT * FROM schedule_working WHERE year=? AND month=? LIMIT 1
      - Map DB row → {
            "participant_doctor_ids": [...],
            "assignments": [...],   # normalized!
            "meta": {...},
            "updated_at": <UTC datetime>,
            "lock_version": <int>   # hard OCC counter
        }
    """
    # MVP: always ensure a seed working row exists so FE has a stable shape.
    return _ensure_seed(year, month)


def get_working_lock_version(year: int, month: int) -> Optional[int]:
    """
    Return current lock_version for the working row, or None if missing.

    Why this exists:
      - Routers/tests can call a simple accessor (doesn't leak data).
    Post-ORM:
      - SELECT lock_version FROM schedule_working WHERE year=? AND month=? LIMIT 1
    """
    w = get_working(year, month)
    return w["lock_version"] if w else None


def get_pointer_version_id(
    year: int,
    month: int,
    target: Literal["draft", "published"],
) -> Optional[str]:
    """
    Return version_id pointed by the 'draft' or 'published' pointer for the period.

    Post-ORM:
      - SELECT draft_version_id, published_version_id
        FROM schedule_pointers WHERE year=? AND month=? LIMIT 1
    """
    # MVP behavior to keep diagnostics endpoint functional:
    if target == "draft":
        # pretend there is a current draft version (used by diagnostics stub)
        return f"schv_{year}_{str(month).zfill(2)}_0003"
    if target == "published":
        # no published by default in MVP (admin can still publish via router stub)
        return None
    return None


def get_published_pointer(year: int, month: int) -> Optional[str]:
    """
    Convenience wrapper for the 'published' pointer.

    Post-ORM:
      - SELECT published_version_id FROM schedule_pointers
        WHERE year=? AND month=? LIMIT 1
    """
    return get_pointer_version_id(year, month, target="published")


def list_my_assignments_from_published(year: int, month: int, doctor_id: int) -> Optional[List[Dict[str, Any]]]:
    """
    Return a filtered list of assignments (day + shift_type) for the given doctor
    from the *current published* version.

    MVP:
      - We do not emulate published content here → return None so the router
        responds with 404 when there is no published pointer.
    Post-ORM:
      1) Resolve `published_version_id` via pointer.
      2) SELECT payload FROM schedule_versions WHERE version_id=? AND kind='published'
      3) Filter assignments where assignment['doctor_id'] == doctor_id.
      4) Return [{"day": int, "shift_type": "on_duty"|"on_call"}, ...]
    """
    # Until ORM is in place we signal "no published" to the router.
    ver = get_published_pointer(year, month)
    if ver is None:
        return None

    # When ORM lands, implement SELECT payload and filter here.
    return None  # placeholder


# ==============================================================================
# WRITE flows — autosave & snapshots
# ==============================================================================


def save_working_autosave(
    year: int,
    month: int,
    assignments: List[Dict[str, Any]] | List[Any],
    meta: Optional[Dict[str, Any]] = None,
    if_match_lock_version: Optional[int] = None,
) -> Tuple[datetime, int]:
    """
    Persist 'working' changes WITHOUT creating a checkpoint (autosave) using hard OCC.

    Policy (hard OCC with integer lock_version):
      - Client may send if_match_lock_version.
      - Server compares it to current lock_version:
          * if present and mismatch -> raise 409 (router maps ValueError('edit_conflict'))
          * if absent -> allow (MVP policy).
      - On success: normalize + save + increment lock_version by 1.

    Returns:
        (updated_at: datetime, new_lock_version: int)

    Raises:
        ValueError("period_closed") — mutating past periods is forbidden.
        ValueError("edit_conflict")  — OCC mismatch.
    """
    # Defense-in-depth time guard.
    _ensure_editable_or_raise(year, month)

    # MVP store
    row = _ensure_seed(year, month)

    # OCC check (only if client provided a version)
    current_lv = int(row["lock_version"])
    if if_match_lock_version is not None and int(if_match_lock_version) != current_lv:
        # Router will convert this into HTTP 409; we raise a simple exception here.
        raise ValueError("edit_conflict")

    # Normalize assignments before persisting (prevents duplicates / false diffs)
    normalized = normalize_assignments(assignments)

    # Persist into our MVP in-memory row
    row["assignments"] = normalized
    row["meta"] = meta or row.get("meta", {})
    row["updated_at"] = now_utc()
    row["lock_version"] = current_lv + 1  # hard OCC bump

    return row["updated_at"], row["lock_version"]


def snapshot_working(year: int, month: int) -> Dict[str, Any]:
    """
    Produce a snapshot copy of 'working' that can be persisted as an immutable version.

    Used by:
      - On checkpoint creation.
      - On publish (freeze the current working as versioned payload).

    Important:
      - We ALWAYS normalize the assignment list so versions are comparable and
        exports are stable/deterministic.
    """
    w = get_working(year, month) or {
        "participant_doctor_ids": [],
        "assignments": [],
        "meta": {"labels": []},
        "updated_at": now_utc(),
        "lock_version": 1,
    }
    # Critical: freeze a normalized snapshot to keep versions comparable
    w = dict(w)  # shallow copy
    w["assignments"] = normalize_assignments(w.get("assignments", []))
    return w


# ==============================================================================
# FUTURE ORM FLOWS — skeletons with detailed TODOs.
# They currently raise NotImplementedError so we don't silently do partial work.
# Routers can be wired later to call them when ORM is ready.
# ==============================================================================


def create_draft_checkpoint(year: int, month: int, note: Optional[str] = None) -> Dict[str, Any]:
    """
    Save explicit checkpoint from current working and move the DRAFT pointer.

    Pipeline (post-ORM):
      1) _ensure_editable_or_raise(year, month)
      2) SELECT * FROM schedule_working WHERE {y,m} FOR UPDATE
      3) Normalize assignments (ALWAYS use normalize_assignments)
      4) INSERT INTO schedule_versions(kind='draft_checkpoint', payload, created_by, note, created_at)
      5) UPDATE schedule_pointers SET draft_version_id=?, updated_at=NOW()
      6) Prune to FIFO(5) oldest draft checkpoints for {y,m}
      7) UPSERT diagnostics for this version (or mark 'stale' → compute async/lazy)
      8) Return: dict matching schemas.ScheduleCheckpointCreated.draft + diagnostics
    """
    _ensure_editable_or_raise(year, month)
    raise NotImplementedError("create_draft_checkpoint (ORM skeleton)")


def move_draft_pointer(year: int, month: int, direction: Literal["prev", "next"]) -> Dict[str, Any]:
    """
    Move draft pointer to previous/next checkpoint (global admin stream).

    Pipeline (post-ORM):
      1) _ensure_editable_or_raise(year, month)
      2) Resolve current draft_version_id from schedule_pointers
      3) Find previous/next version (ORDER BY created_at)
      4) If none → raise ValueError('cannot_undo' / 'cannot_redo')
      5) UPDATE schedule_pointers SET draft_version_id=target
      6) OVERWRITE schedule_working from target.payload (to keep editing buffer in sync)
      7) Return current draft snapshot + working + diagnostics(target)
    """
    _ensure_editable_or_raise(year, month)
    raise NotImplementedError("move_draft_pointer (ORM skeleton)")


def publish_from_working(
    year: int,
    month: int,
    *,
    force: bool = False,
    accepted_exceptions: Optional[List[Dict[str, Any]]] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Validate hard rules, optionally accept exceptions, then publish current working.

    Pipeline (post-ORM):
      1) _ensure_editable_or_raise(year, month)
      2) SELECT working FOR UPDATE; normalize assignments
      3) Run HARD-RULE validator on working snapshot
         - If violations and not force → raise ValueError('publish_blocked_by_hard_rules',
             context={'violations': [...]})
      4) If force → persist accepted_exceptions into payload.meta.exceptions[]
         (append with audit: accepted_by_user_id, accepted_at)
      5) INSERT INTO schedule_versions(kind='published', payload, audit_note, published_by, published_at)
      6) UPDATE schedule_pointers SET published_version_id=?, updated_at=NOW()
      7) Prune to FIFO(5) oldest published snapshots for {y,m}
      8) UPSERT diagnostics for the new published version
      9) Return structure for schemas.SchedulePublishCreated
    """
    _ensure_editable_or_raise(year, month)
    raise NotImplementedError("publish_from_working (ORM skeleton)")


def move_published_pointer(year: int, month: int, direction: Literal["prev", "next"]) -> Dict[str, Any]:
    """
    Roll back / redo published pointer within the editing window.

    Pipeline (post-ORM):
      1) _ensure_editable_or_raise(year, month)
      2) Resolve current published_version_id from schedule_pointers
      3) Find prev/next published snapshot
      4) If none → raise ValueError('cannot_undo' / 'cannot_redo')
      5) UPDATE schedule_pointers SET published_version_id=target
      6) Return published snapshot block (schemas.SchedulePublishedView)
    """
    _ensure_editable_or_raise(year, month)
    raise NotImplementedError("move_published_pointer (ORM skeleton)")


__all__ = [
    # READ helpers
    "get_working",
    "get_working_lock_version",
    "get_pointer_version_id",
    "get_published_pointer",
    "list_my_assignments_from_published",
    # WRITE / autosave
    "save_working_autosave",
    "snapshot_working",
    # ORM skeletons (future)
    "create_draft_checkpoint",
    "move_draft_pointer",
    "publish_from_working",
    "move_published_pointer",
]
