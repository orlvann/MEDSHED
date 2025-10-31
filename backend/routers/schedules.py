# backend/routers/schedules.py
# Schedules router — MVP contract endpoints (Admin & Doctor paths).
#
# Goals:
# - Keep routers thin (I/O only). Move business logic to services post-MVP.
# - Enforce a single normalization pipeline in services for any write/snapshot.
# - Provide consistent API shapes (DTOs) and HTTP codes.
# - Centralize time policy via utils/timez (no ad-hoc time logic here).
# - Prepare hooks for RBAC and OCC (already present in DTOs).
#
# Endpoints (MVP):
#   ADMIN:
#     - POST  /api/v1/schedules/generate
#     - GET   /api/v1/schedules/{year}/{month}                    (Period View)
#     - GET   /api/v1/schedules/{year}/{month}/working            (read working)
#     - PUT   /api/v1/schedules/{year}/{month}/working            (autosave working)
#     - POST  /api/v1/schedules/{year}/{month}/checkpoint         (Save → draft checkpoint + diagnostics)
#     - POST  /api/v1/schedules/{year}/{month}/revert-last        (draft UNDO)
#     - POST  /api/v1/schedules/{year}/{month}/revert-next        (draft REDO)
#     - POST  /api/v1/schedules/{year}/{month}/publish            (publish from working; force supported)
#     - POST  /api/v1/schedules/{year}/{month}/revert-last-published
#     - POST  /api/v1/schedules/{year}/{month}/revert-next-published
#     - GET   /api/v1/schedules/{year}/{month}/diagnostics?target=draft|published
#
#   DOCTOR (read-only):
#     - GET   /api/v1/schedules/{year}/{month}/published
#     - GET   /api/v1/schedules/{year}/{month}/my-assignments
#     - GET   /api/v1/schedules/export?year=&month=&mode=published&format=xlsx|pdf
#
# Notes:
# - Status 201 on: generate, checkpoint, publish.
# - Status 409 on: edit_conflict, publish_blocked_by_hard_rules, cannot_undo/redo (when implemented).
# - Status 404 when a pointer is missing (diagnostics/published).
# - Status 403 (TODO) for period-closed edits post-MVP.
# - RBAC via require_admin / require_doctor.

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status

# DTOs
from backend.models.schemas.diagnostics import DiagnosticsRead
from backend.models.schemas.dto_common import make_error
from backend.models.schemas.schedule import (
    MyAssignmentsRead,
    ScheduleCheckpointCreated,
    ScheduleCheckpointRequest,
    ScheduleGenerateCreated,
    ScheduleGenerateRequest,
    SchedulePublishCreated,
    SchedulePublishedRead,
    SchedulePublishedRevertRead,
    SchedulePublishRequest,
    ScheduleRevertRead,
    SchedulesPeriodViewRead,
    ScheduleWorkingAck,
    ScheduleWorkingPut,
    ScheduleWorkingRead,
)

# RBAC placeholders (post-MVP: real auth/JWT)
from backend.routers.deps import UserCtx, require_admin, require_doctor

# Services (MVP stubs now; ORM later)
from backend.services.scheduling_service import (
    get_pointer_version_id,
    get_published_pointer,
    get_working,
    list_my_assignments_from_published,
    save_working_autosave,
    snapshot_working,
)

# Time policy
from backend.utils import ORG_TZ, get_period_status, now_utc

# post-MVP period guard
# from backend.utils import is_period_closed

router = APIRouter(prefix="/api/v1/schedules")  # per-route tags to avoid duplicates


# ------------------------------------------------------------------------------
# ADMIN — Generate (working + first draft checkpoint + diagnostics)
# ------------------------------------------------------------------------------
@router.post(
    "/generate",
    status_code=status.HTTP_201_CREATED,
    response_model=ScheduleGenerateCreated,
    summary="Generate schedule: writes working + creates first draft checkpoint",
    tags=["schedules:admin"],
    operation_id="schedules_generate",
)
def generate_schedule(
    body: ScheduleGenerateRequest = Body(...),
    user: UserCtx = Depends(require_admin),
):
    """
    MVP stub:
    - Return deterministic shape: working + first draft checkpoint + diagnostics.
    - No real solver/DB yet.

    Post-MVP (services/ORM):
    - Load active doctors/preferences → run solver → persist working.
    - Create version(kind='draft_checkpoint') + set draft pointer.
    - Compute diagnostics for this version and persist cache.
    - Audit (created_by_user_id = user.user_id).
    """
    # TODO: if is_period_closed(body.year, body.month) → raise 403 'period_closed'
    now = now_utc()
    year, month = int(body.year), int(body.month)
    first_ver = f"schv_{year}_{str(month).zfill(2)}_0001"

    return {
        "year": year,
        "month": month,
        "status": "draft",
        "working": {
            "year": year,
            "month": month,
            "exists": True,
            "participant_doctor_ids": body.participant_doctor_ids or [1, 2, 5, 7],
            "assignments": [],
            "meta": {"labels": ["as_generated"]},
            "updated_at": now,
            "lock_version": 1,
        },
        "draft": {
            "version_id": first_ver,
            "checkpoints_count": 1,
            "can_undo": False,
            "can_redo": False,
            "payload": {
                "participant_doctor_ids": body.participant_doctor_ids or [1, 2, 5, 7],
                "assignments": [],
                "meta": {"labels": ["as_generated"], "exceptions": []},
            },
        },
        "diagnostics": {
            "version_id": first_ver,
            "computed_at": now,
            "summary": {
                "penalty_total": 0,
                "understaffed_days": 0,
                "rest_violations": 0,
                "fairness_index": 1.0,
                "preference_fulfillment_pct": 100.0,
            },
        },
    }


# ------------------------------------------------------------------------------
# ADMIN — Period View (working + pointers + diagnostics)
# ------------------------------------------------------------------------------
@router.get(
    "/{year}/{month}",
    response_model=SchedulesPeriodViewRead,
    summary="Period view (working + draft pointer + published pointer + diagnostics)",
    tags=["schedules:admin"],
    operation_id="schedules_period_view",
)
def schedules_period_view(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    user: UserCtx = Depends(require_admin),
):
    """
    Return a unified period view for the Schedules tab.

    Policy (MVP):
    - Always return 200 with a skeleton when no data exists yet.
    - 'working.exists' = False, pointers null, diagnostics None.
    """
    period_status = get_period_status(year, month)
    now = now_utc()

    w = get_working(year, month)  # MVP in-memory seed
    if not w:
        return {
            "year": year,
            "month": month,
            "org_timezone": ORG_TZ,
            "period_status": period_status,
            "view": {"default_mode": "draft", "toggle_available": False},
            "working": {
                "year": year,
                "month": month,
                "exists": False,
                "participant_doctor_ids": [],
                "assignments": [],
                "meta": {"labels": []},
                "updated_at": None,
                "lock_version": None,
            },
            "draft": {
                "version_id": None,
                "checkpoints_count": 0,
                "can_undo": False,
                "can_redo": False,
                "payload": None,
            },
            "published": {
                "version_id": None,
                "publications_count": 0,
                "can_undo": False,
                "can_redo": False,
                "payload": None,
            },
            "diagnostics": None,
        }

    draft_ver = f"schv_{year}_{str(month).zfill(2)}_0003"
    return {
        "year": year,
        "month": month,
        "org_timezone": ORG_TZ,
        "period_status": period_status,
        "view": {"default_mode": "draft", "toggle_available": True},
        "working": {
            "year": year,
            "month": month,
            "exists": True,
            "participant_doctor_ids": w.get("participant_doctor_ids", []),
            "assignments": w.get("assignments", []),
            "meta": w.get("meta", {"labels": []}),
            "updated_at": w.get("updated_at", now),
            "lock_version": w.get("lock_version", 1),
        },
        "draft": {
            "version_id": draft_ver,
            "checkpoints_count": 3,
            "can_undo": True,
            "can_redo": False,
            "payload": {
                "participant_doctor_ids": w.get("participant_doctor_ids", []),
                "assignments": [],
                "meta": {"labels": ["as_generated"], "exceptions": []},
            },
        },
        "published": {
            "version_id": None,
            "publications_count": 0,
            "can_undo": False,
            "can_redo": False,
            "payload": None,
        },
        "diagnostics": {
            "version_id": draft_ver,
            "computed_at": now,
            "summary": {
                "penalty_total": 42,
                "understaffed_days": 1,
                "rest_violations": 0,
                "fairness_index": 0.92,
                "preference_fulfillment_pct": 86.5,
            },
        },
    }


# ------------------------------------------------------------------------------
# ADMIN — Working (read & autosave)
# ------------------------------------------------------------------------------
@router.get(
    "/{year}/{month}/working",
    response_model=ScheduleWorkingRead,
    summary="Read working draft (explicit)",
    tags=["schedules:admin"],
    operation_id="schedules_working_read",
)
def schedules_working_read(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    user: UserCtx = Depends(require_admin),
):
    """Return current working draft or a skeleton with exists=False."""
    w = get_working(year, month)
    if not w:
        return {
            "year": year,
            "month": month,
            "exists": False,
            "participant_doctor_ids": [],
            "assignments": [],
            "meta": {"labels": []},
            "updated_at": None,
            "lock_version": None,
        }
    return {
        "year": year,
        "month": month,
        "exists": True,
        "participant_doctor_ids": w.get("participant_doctor_ids", []),
        "assignments": w.get("assignments", []),
        "meta": w.get("meta", {"labels": []}),
        "updated_at": w.get("updated_at"),
        "lock_version": w.get("lock_version", 1),
    }


@router.put(
    "/{year}/{month}/working",
    response_model=ScheduleWorkingAck,
    summary="Autosave working (no checkpoint, OCC prepared via lock_version)",
    tags=["schedules:admin"],
    operation_id="schedules_working_put",
)
def schedules_working_put(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    body: ScheduleWorkingPut = Body(...),
    user: UserCtx = Depends(require_admin),
):
    """
    Behavior:
    - Delegates to service which normalizes assignments and applies hard OCC:
      * if 'if_match_lock_version' mismatches → raises 'edit_conflict' → 409
      * if absent → allow (MVP policy)
    - Returns lean ACK (year, month, updated_at, lock_version).
    """
    # TODO: if is_period_closed(...) → raise 403 'period_closed'
    try:
        updated_at, new_lv = save_working_autosave(
            year=year,
            month=month,
            assignments=[a.model_dump() for a in body.assignments],
            meta=body.meta,
            if_match_lock_version=body.if_match_lock_version,
        )
    except ValueError as e:
        if str(e) == "edit_conflict":
            raise HTTPException(status_code=409, detail=make_error("edit_conflict"))
        raise

    return {"year": year, "month": month, "updated_at": updated_at, "lock_version": new_lv}


# ------------------------------------------------------------------------------
# ADMIN — Draft checkpoint (Save) — creates version + diagnostics
# ------------------------------------------------------------------------------
@router.post(
    "/{year}/{month}/checkpoint",
    status_code=status.HTTP_201_CREATED,
    response_model=ScheduleCheckpointCreated,
    summary="Create draft checkpoint from working (+diagnostics)",
    tags=["schedules:admin"],
    operation_id="schedules_checkpoint",
)
def schedules_checkpoint(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    body: ScheduleCheckpointRequest | None = Body(None),
    user: UserCtx = Depends(require_admin),
):
    """
    MVP stub:
    - Create a synthetic draft pointer + diagnostics from current working.
    Post-MVP:
    - Persist version(kind='draft_checkpoint'), update pointer (FIFO=5), compute & store diagnostics.
    """
    # TODO: if is_period_closed(...) → raise 403 'period_closed'
    now = now_utc()
    ver = f"schv_{year}_{str(month).zfill(2)}_0002"
    w = snapshot_working(year, month)

    return {
        "year": year,
        "month": month,
        "draft": {
            "version_id": ver,
            "checkpoints_count": 2,
            "can_undo": True,
            "can_redo": False,
            "payload": {
                "participant_doctor_ids": w.get("participant_doctor_ids", []),
                "assignments": w.get("assignments", []),
                "meta": {"labels": ["as_generated", "touched"], "exceptions": []},
            },
        },
        "diagnostics": {
            "version_id": ver,
            "computed_at": now,
            "summary": {
                "penalty_total": 38,
                "understaffed_days": 0,
                "rest_violations": 0,
                "fairness_index": 0.94,
                "preference_fulfillment_pct": 88.0,
            },
        },
    }


# ------------------------------------------------------------------------------
# ADMIN — Draft UNDO / REDO — pointer moves + working overwrite
# ------------------------------------------------------------------------------
@router.post(
    "/{year}/{month}/revert-last",
    response_model=ScheduleRevertRead,
    summary="Draft UNDO (pointer → previous checkpoint + overwrite working)",
    tags=["schedules:admin"],
    operation_id="schedules_draft_undo",
)
def schedules_draft_undo(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    user: UserCtx = Depends(require_admin),
):
    """
    MVP stub:
    - Move pointer back, copy its payload into 'working', return draft + working + diagnostics.
    """
    # TODO: if is_period_closed(...) → raise 403 'period_closed'
    now = now_utc()
    ver = f"schv_{year}_{str(month).zfill(2)}_0001"
    w = snapshot_working(year, month)

    return {
        "year": year,
        "month": month,
        "draft": {
            "version_id": ver,
            "checkpoints_count": 2,
            "can_undo": False,
            "can_redo": True,
            "payload": {
                "participant_doctor_ids": w.get("participant_doctor_ids", []),
                "assignments": [],
                "meta": {"labels": ["as_generated"], "exceptions": []},
            },
        },
        "working": {
            "year": year,
            "month": month,
            "exists": True,
            "participant_doctor_ids": w.get("participant_doctor_ids", []),
            "assignments": [],
            "meta": {"labels": ["as_generated"]},
            "updated_at": now,
            "lock_version": w.get("lock_version", 1),
        },
        "diagnostics": {
            "version_id": ver,
            "computed_at": now,
            "summary": {
                "penalty_total": 42,
                "understaffed_days": 1,
                "rest_violations": 0,
                "fairness_index": 0.92,
                "preference_fulfillment_pct": 86.5,
            },
        },
    }


@router.post(
    "/{year}/{month}/revert-next",
    response_model=ScheduleRevertRead,
    summary="Draft REDO (pointer → next checkpoint + overwrite working)",
    tags=["schedules:admin"],
    operation_id="schedules_draft_redo",
)
def schedules_draft_redo(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    user: UserCtx = Depends(require_admin),
):
    """
    MVP stub:
    - Move pointer forward, copy its payload into 'working', return draft + working + diagnostics.
    """
    # TODO: if is_period_closed(...) → raise 403 'period_closed'
    now = now_utc()
    ver = f"schv_{year}_{str(month).zfill(2)}_0002"
    w = snapshot_working(year, month)

    return {
        "year": year,
        "month": month,
        "draft": {
            "version_id": ver,
            "checkpoints_count": 2,
            "can_undo": True,
            "can_redo": False,
            "payload": {
                "participant_doctor_ids": w.get("participant_doctor_ids", []),
                "assignments": [],
                "meta": {"labels": ["as_generated", "touched"], "exceptions": []},
            },
        },
        "working": {
            "year": year,
            "month": month,
            "exists": True,
            "participant_doctor_ids": w.get("participant_doctor_ids", []),
            "assignments": [],
            "meta": {"labels": ["as_generated", "touched"]},
            "updated_at": now,
            "lock_version": w.get("lock_version", 1),
        },
        "diagnostics": {
            "version_id": ver,
            "computed_at": now,
            "summary": {
                "penalty_total": 38,
                "understaffed_days": 0,
                "rest_violations": 0,
                "fairness_index": 0.94,
                "preference_fulfillment_pct": 88.0,
            },
        },
    }


# ------------------------------------------------------------------------------
# ADMIN — Publish (from working) with hard-rule guard
# ------------------------------------------------------------------------------
@router.post(
    "/{year}/{month}/publish",
    status_code=status.HTTP_201_CREATED,
    response_model=SchedulePublishCreated,
    summary="Publish from working (hard-rule guard; force supported)",
    tags=["schedules:admin"],
    operation_id="schedules_publish",
)
def schedules_publish(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    body: SchedulePublishRequest = Body(...),
    user: UserCtx = Depends(require_admin),
):
    """
    Behavior:
    - If force=false and hard violations detected → 409 {"detail":"publish_blocked_by_hard_rules", "violations":[...]}
    - If force=true → accept and persist accepted_exceptions into payload.meta.exceptions[] with audit.
    """
    # TODO: if is_period_closed(...) → raise 403 'period_closed'
    now = now_utc()

    # Stub: simulate violations found
    violations = [
        {"code": "NO_SPECIALIST_DAY_12", "message": "No specialist on 12th"},
        {"code": "MAX_CONSEC_ONCALL_EXCEEDED_DAY_20", "message": "Exceeded consecutive on-call limit on 20th"},
    ]
    if not body.force:
        raise HTTPException(
            status_code=409,
            detail=make_error("publish_blocked_by_hard_rules", context={"violations": violations}),
        )

    ver = f"schv_{year}_{str(month).zfill(2)}_0101"
    w = snapshot_working(year, month)

    exceptions = [
        {"code": e.code, "justification": e.justification, "accepted_by_user_id": user.user_id, "accepted_at": now}
        for e in body.accepted_exceptions
    ]

    return {
        "year": year,
        "month": month,
        "published": {
            "version_id": ver,
            "audit": {"published_at": now, "published_by_user_id": user.user_id, "note": body.note or "Finalize"},
            "publications_count": 1,
            "can_undo": False,
            "can_redo": False,
            "payload": {
                "participant_doctor_ids": w.get("participant_doctor_ids", []),
                "assignments": w.get("assignments", []),  # post-MVP: frozen normalized working
                "meta": {"labels": ["as_generated", "touched"], "exceptions": exceptions},
            },
        },
    }


# ------------------------------------------------------------------------------
# ADMIN — Published UNDO / REDO (pointer moves only)
# ------------------------------------------------------------------------------
@router.post(
    "/{year}/{month}/revert-last-published",
    response_model=SchedulePublishedRevertRead,
    summary="Published rollback (pointer → previous published)",
    tags=["schedules:admin"],
    operation_id="schedules_published_undo",
)
def schedules_published_undo(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    user: UserCtx = Depends(require_admin),
):
    # TODO: if is_period_closed(...) → raise 403 'period_closed'
    ver = f"schv_{year}_{str(month).zfill(2)}_0100"
    w = snapshot_working(year, month)
    return {
        "year": year,
        "month": month,
        "published": {
            "version_id": ver,
            "publications_count": 2,
            "can_undo": False,
            "can_redo": True,
            "payload": {
                "participant_doctor_ids": w.get("participant_doctor_ids", []),
                "assignments": [],
                "meta": {"labels": ["as_generated", "touched"], "exceptions": []},
            },
        },
    }


@router.post(
    "/{year}/{month}/revert-next-published",
    response_model=SchedulePublishedRevertRead,
    summary="Published redo (pointer → next published)",
    tags=["schedules:admin"],
    operation_id="schedules_published_redo",
)
def schedules_published_redo(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    user: UserCtx = Depends(require_admin),
):
    # TODO: if is_period_closed(...) → raise 403 'period_closed'
    ver = f"schv_{year}_{str(month).zfill(2)}_0101"
    w = snapshot_working(year, month)
    return {
        "year": year,
        "month": month,
        "published": {
            "version_id": ver,
            "publications_count": 2,
            "can_undo": True,
            "can_redo": False,
            "payload": {
                "participant_doctor_ids": w.get("participant_doctor_ids", []),
                "assignments": [],
                "meta": {"labels": ["as_generated", "touched"], "exceptions": []},
            },
        },
    }


# ------------------------------------------------------------------------------
# ADMIN — Diagnostics (per pointer)
# ------------------------------------------------------------------------------
@router.get(
    "/{year}/{month}/diagnostics",
    response_model=DiagnosticsRead,
    summary="Diagnostics for draft or published (per pointer)",
    tags=["schedules:admin"],
    operation_id="schedules_diagnostics",
)
def schedules_diagnostics(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    target: Literal["draft", "published"] = Query(..., description="Which pointer to read diagnostics for"),
    user: UserCtx = Depends(require_admin),
):
    """
    Behavior:
    - Look up version_id via pointer (draft/published). If missing → 404.
    - Return diagnostics (MVP stub). Post-MVP: compute lazily and persist cache.
    """
    version_id = get_pointer_version_id(year, month, target=target)
    if not version_id:
        raise HTTPException(status_code=404, detail=make_error("not_found", context={"target": target}))

    return {
        "version_id": version_id,
        "computed_at": now_utc(),
        "summary": {
            "penalty_total": 38,
            "understaffed_days": 0,
            "rest_violations": 0,
            "fairness_index": 0.94,
            "preference_fulfillment_pct": 88.0,
        },
    }


# ------------------------------------------------------------------------------
# DOCTOR — Unified Export (published only in practice; shown once in docs)
# ------------------------------------------------------------------------------
@router.get(
    "/export",
    summary="Unified export (draft|published) to xlsx|pdf",
    tags=["schedules:doctor"],  # show only once in Swagger (do not duplicate in admin group)
    operation_id="schedules_export",
)
def schedules_export(
    year: int = Query(..., ge=1900, le=2100),
    month: int = Query(..., ge=1, le=12),
    mode: Literal["draft", "published"] = Query(..., description="Export from 'working draft' or current 'published'"),
    file_format: Literal["xlsx", "pdf"] = Query(..., description="File format", alias="format"),  # URL uses ?format=...
    doctor_id: int | None = Query(None, description="Reserved (e.g., personal calendar export)"),
    user: UserCtx = Depends(require_doctor),  # doctors AND admins allowed
):
    """
    Exports are generated from a frozen version referenced by POINTER (draft|published),
    never from the mutable 'working' buffer.
    RBAC nuance:
    - Doctors may export only 'published' and only as xlsx/pdf.
    - Admins can export both modes; keeping single docs section avoids duplication.
    """
    if user.role == "doctor" and mode != "published":
        raise HTTPException(status_code=403, detail=make_error("forbidden"))

    # Resolve source version via POINTER (not working)
    pointer = "draft" if mode == "draft" else "published"
    version_id = get_pointer_version_id(year, month, target=pointer)
    if not version_id:
        raise HTTPException(status_code=404, detail=make_error("not_found", context={"target": pointer}))

    # MVP JSON stub (binary stream post-MVP)
    return {
        "detail": "stub: export stream here",
        "year": year,
        "month": month,
        "mode": mode,
        "format": file_format,
        "doctor_id": doctor_id,
        "version_id": version_id,
        "source": {"type": "pointer", "target": pointer},
    }


# ------------------------------------------------------------------------------
# DOCTOR — Read published & My assignments
# ------------------------------------------------------------------------------
@router.get(
    "/{year}/{month}/published",
    summary="Read current PUBLISHED schedule for the period (pointer-based)",
    response_model=SchedulePublishedRead,
    tags=["schedules:doctor"],
    operation_id="schedules_published_read",
)
def schedules_published_read(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    user: UserCtx = Depends(require_doctor),
):
    """
    Return the currently published schedule snapshot for {year,month}.
    - 404 if there is no published pointer for the period.
    - Admins can also call this to preview live data.
    """
    ver = get_published_pointer(year, month)
    if ver is None:
        raise HTTPException(status_code=404, detail=make_error("not_found", context={"target": "published"}))

    now = now_utc()
    snap = snapshot_working(year, month)  # MVP stand-in for published payload
    return {
        "year": year,
        "month": month,
        "org_timezone": ORG_TZ,
        "period_status": get_period_status(year, month),
        "published": {
            "version_id": ver,
            "publications_count": 1,
            "can_undo": False,
            "can_redo": False,
            "audit": {"published_at": now, "published_by_user_id": 101, "note": "MVP stub"},
            "payload": {
                "participant_doctor_ids": snap.get("participant_doctor_ids", []),
                "assignments": snap.get("assignments", []),
                "meta": {"labels": ["as_generated"], "exceptions": []},
            },
        },
    }


@router.get(
    "/{year}/{month}/my-assignments",
    summary="List my assignments from the current PUBLISHED schedule",
    response_model=MyAssignmentsRead,
    tags=["schedules:doctor"],
    operation_id="schedules_my_assignments",
)
def schedules_my_assignments(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    user: UserCtx = Depends(require_doctor),
):
    """
    Return only the caller's assignments (day + shift_type) from the *published* schedule.
    - 404 if no published schedule exists for the period.
    """
    mine = list_my_assignments_from_published(year, month, doctor_id=user.user_id)
    if mine is None:
        raise HTTPException(status_code=404, detail=make_error("not_found", context={"target": "published"}))
    return {"doctor_id": user.user_id, "year": year, "month": month, "assignments": mine}
