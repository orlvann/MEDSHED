# backend/routers/schedules.py
# Schedules router — Admin & Doctor paths (thin, typed, no business logic).
#
# LAYER CONTRACT
# --------------
# - This router performs I/O: request/response validation, RBAC, HTTP codes.
# - All domain logic and DB writes/reads live in services.SchedulingService.
# - Errors from service are raised as ValueError with a short code; _raise()
#   maps them to HTTP responses consistently.
#
# ERROR MAPPING (ValueError.code -> HTTP)
# ---------------------------------------
# - "period_closed"                       -> 403
# - "edit_conflict"                       -> 409
# - "cannot_undo" / "cannot_redo"         -> 409
# - "publish_blocked_by_hard_rules"       -> 409
# - "not_found"                           -> 404
#
# API SHAPE
# ---------
# - DTOs are defined in backend/models/schemas/schedule.py (framework agnostic).
# - All responses are typed with response_model=... for stable Swagger/OpenAPI.
# - Status codes:
#     * 201 on generate / checkpoint / publish
#     * 200 on reads and revert endpoints
#
# TIME & ENUMS
# ------------
# - org timezone is provided by ORG_TZ.
# - period_status is derived via get_period_status and cast to PeriodStatus enum.
#
# SECURITY / RBAC (MVP)
# ---------------------
# - Admin-only: generate, working read/put, checkpoint, revert, publish.
# - Doctor: can read current published and (later) export personal data.
# - Auth/JWT is stubbed; require_admin / require_doctor simulate roles.

from __future__ import annotations

from typing import Literal, Optional, cast

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status

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
from backend.routers.deps import UserCtx, require_admin, require_doctor
from backend.services import SchedulingService

router = APIRouter(prefix="/api/v1/schedules")
svc = SchedulingService()


def _raise(e: ValueError) -> None:
    """
    Convert domain ValueError(code) -> HTTPException.

    This keeps the router declarative and avoids duplicating try/except logic.
    """
    code = str(e)
    mapping = {
        "period_closed": status.HTTP_403_FORBIDDEN,
        "edit_conflict": status.HTTP_409_CONFLICT,
        "cannot_undo": status.HTTP_409_CONFLICT,
        "cannot_redo": status.HTTP_409_CONFLICT,
        "publish_blocked_by_hard_rules": status.HTTP_409_CONFLICT,
        "not_found": status.HTTP_404_NOT_FOUND,
    }
    if code in mapping:
        raise HTTPException(status_code=mapping[code], detail=make_error(code))
    raise e


# ------------------------------- ADMIN: generate -------------------------------
@router.post(
    "/generate",
    status_code=status.HTTP_201_CREATED,
    response_model=ScheduleGenerateCreated,
    tags=["schedules:admin"],
    summary="Generate schedule: writes working + creates first draft checkpoint",
)
def generate_schedule(
    body: ScheduleGenerateRequest = Body(...),
    user: UserCtx = Depends(require_admin),
) -> ScheduleGenerateCreated:
    """
    Generate a new schedule for {year, month} (MVP: seed + first checkpoint).
    """
    try:
        return svc.generate(body, user_id=user.user_id if user else None)
    except ValueError as e:
        _raise(e)
        assert False  # for type checker


# --------------------------- ADMIN: diagnostics --------------------------
@router.get(
    "/{year}/{month}/diagnostics",
    response_model=DiagnosticsRead,
    tags=["schedules:admin"],
    summary="Diagnostics for draft or published (per pointer)",
    operation_id="schedules_diagnostics_get",
)
def schedules_diagnostics(
    user: UserCtx = Depends(require_admin),  # RBAC: admin only (dopasuj do swojej polityki)
    year: int = Path(..., ge=1900, le=2100, description="Calendar year"),
    month: int = Path(..., ge=1, le=12, description="Month 1..12"),
    target: Literal["draft", "published"] = Query(..., description="Which pointer to use"),
):
    """
    Thin router layer: call SchedulingService (source of truth for pointers).

    MVP behavior:
    - Resolve {year, month, target} → pointer → version_id.
    - Compute or refresh cached diagnostics for that version (current MVP returns zeros).
    - Return compact DiagnosticsRead (summary KPIs; 'details' is None in MVP).
    """
    try:
        return svc.get_diagnostics(year=year, month=month, target=target)
    except ValueError as e:
        code = str(e)
        if code in {"not_found"}:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=make_error("not_found", context={"year": year, "month": month, "target": target}),
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=make_error(code or "bad_request"))


# --------------------------- ADMIN: period view (MVP) --------------------------
@router.get(
    "/{year}/{month}",
    response_model=SchedulesPeriodViewRead,
    tags=["schedules:admin"],
    summary="Period view (working + pointers + diagnostics) — service-built",
)
def schedules_period_view(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    user: UserCtx = Depends(require_admin),
) -> SchedulesPeriodViewRead:
    """
    Thin router: delegate composition to SchedulingService.get_period_view.
    Router no longer composes the view; it calls the service and maps errors.
    """
    try:
        return svc.get_period_view(year, month)
    except ValueError as e:
        _raise(e)
        assert False


# -------------------------- ADMIN: working read/put ----------------------------
@router.get(
    "/{year}/{month}/working",
    response_model=ScheduleWorkingRead,
    tags=["schedules:admin"],
    summary="Read working draft (explicit)",
)
def schedules_working_read(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    user: UserCtx = Depends(require_admin),
) -> ScheduleWorkingRead:
    """
    Return the current working buffer or a skeleton with exists=False.
    """
    try:
        return svc.get_working(year, month)
    except ValueError as e:
        _raise(e)
        assert False


@router.put(
    "/{year}/{month}/working",
    response_model=ScheduleWorkingAck,
    tags=["schedules:admin"],
    summary="Autosave working (OCC via lock_version)",
)
def schedules_working_put(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    body: ScheduleWorkingPut = Body(...),
    user: UserCtx = Depends(require_admin),
) -> ScheduleWorkingAck:
    """
    Autosave the working buffer. If if_match_lock_version mismatches → 409.
    """
    try:
        return svc.save_working(
            year,
            month,
            assignments=body.assignments,
            meta=body.meta,
            if_match_lock_version=body.if_match_lock_version,
            updated_by_user_id=user.user_id if user else None,
        )
    except ValueError as e:
        _raise(e)
        assert False


# ----------------------------- ADMIN: checkpoint -------------------------------
@router.post(
    "/{year}/{month}/checkpoint",
    status_code=status.HTTP_201_CREATED,
    response_model=ScheduleCheckpointCreated,
    tags=["schedules:admin"],
    summary="Create draft checkpoint from working (+diagnostics)",
)
def schedules_checkpoint(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    body: ScheduleCheckpointRequest | None = Body(None),
    user: UserCtx = Depends(require_admin),
) -> ScheduleCheckpointCreated:
    """
    Create an immutable draft version from working and compute diagnostics.
    """
    try:
        return svc.checkpoint(year, month, note=(body.note if body else None), user_id=user.user_id if user else None)
    except ValueError as e:
        _raise(e)
        assert False


# ----------------------------- ADMIN: draft undo/redo --------------------------
@router.post(
    "/{year}/{month}/revert-last",
    response_model=ScheduleRevertRead,
    tags=["schedules:admin"],
    summary="Draft UNDO (pointer → previous checkpoint + overwrite working)",
)
def schedules_draft_undo(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    user: UserCtx = Depends(require_admin),
) -> ScheduleRevertRead:
    """
    Move the draft pointer backward and overwrite working with that snapshot.
    """
    try:
        return cast(
            ScheduleRevertRead,
            svc.revert(year, month, target="draft", direction="prev", user_id=user.user_id if user else None),
        )
    except ValueError as e:
        _raise(e)
        assert False


@router.post(
    "/{year}/{month}/revert-next",
    response_model=ScheduleRevertRead,
    tags=["schedules:admin"],
    summary="Draft REDO (pointer → next checkpoint + overwrite working)",
)
def schedules_draft_redo(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    user: UserCtx = Depends(require_admin),
) -> ScheduleRevertRead:
    """
    Move the draft pointer forward and overwrite working with that snapshot.
    """
    try:
        return cast(
            ScheduleRevertRead,
            svc.revert(year, month, target="draft", direction="next", user_id=user.user_id if user else None),
        )
    except ValueError as e:
        _raise(e)
        assert False


# -------------------------------- ADMIN: publish -------------------------------
@router.post(
    "/{year}/{month}/publish",
    status_code=status.HTTP_201_CREATED,
    response_model=SchedulePublishCreated,
    tags=["schedules:admin"],
    summary="Publish from working (hard-rule guard; force supported)",
)
def schedules_publish(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    body: SchedulePublishRequest = Body(...),
    user: UserCtx = Depends(require_admin),
) -> SchedulePublishCreated:
    """
    Publish the current working snapshot.
    - If force=False and hard violations exist → 409.
    - If force=True → accept exceptions and proceed.
    """
    try:
        return svc.publish(
            year,
            month,
            force=body.force,
            accepted_exceptions=body.accepted_exceptions,
            note=body.note,
            user_id=user.user_id if user else None,
        )
    except ValueError as e:
        _raise(e)
        assert False


# ----------------------- ADMIN: published undo/redo (stub) ---------------------
@router.post(
    "/{year}/{month}/revert-last-published",
    response_model=SchedulePublishedRevertRead,
    tags=["schedules:admin"],
    summary="Published rollback (pointer → previous published)",
)
def schedules_published_undo(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    user: UserCtx = Depends(require_admin),
) -> SchedulePublishedRevertRead:
    """
    Move the published pointer backward (does not touch working).
    """
    try:
        return cast(
            SchedulePublishedRevertRead,
            svc.revert(year, month, target="published", direction="prev", user_id=user.user_id if user else None),
        )
    except ValueError as e:
        _raise(e)
        assert False


@router.post(
    "/{year}/{month}/revert-next-published",
    response_model=SchedulePublishedRevertRead,
    tags=["schedules:admin"],
    summary="Published redo (pointer → next published)",
)
def schedules_published_redo(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    user: UserCtx = Depends(require_admin),
) -> SchedulePublishedRevertRead:
    """
    Move the published pointer forward (does not touch working).
    """
    try:
        return cast(
            SchedulePublishedRevertRead,
            svc.revert(year, month, target="published", direction="next", user_id=user.user_id if user else None),
        )
    except ValueError as e:
        _raise(e)
        assert False


# --------------------------- EXPORT ----------------------------
@router.get(
    "/export",
    tags=["schedules:export"],
    summary="Unified export for admins & doctors (pointer-based, xlsx/pdf/ics)",
    operation_id="schedules_export_get",
)
def schedules_export(
    year: int = Query(..., ge=1900, le=2100, description="Calendar year"),
    month: int = Query(..., ge=1, le=12, description="Month 1..12"),
    mode: Literal["draft", "published"] = Query(..., description="Which stream to export"),
    format: Literal["xlsx", "pdf", "ics"] = Query(..., description="Export format"),
    doctor_id: Optional[int] = Query(None, ge=1, description="Required for ICS (admin may choose a doctor)"),
    user: UserCtx = Depends(require_admin),  # TODO: unify with doctor path rules
):
    """
    Export placeholder.

    IMPORTANT:
    - Keep the path relative ("/export") because router has the prefix "/api/v1/schedules".
    - Tag "schedules:export" creates a separate visual section in Swagger.

    TODO:
    - Implement RBAC rules from API contract (doctors vs admins, ics rules).
    - Stream file with correct headers.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=make_error("not_implemented"))


# --------------------------- DOCTOR: read published ----------------------------
@router.get(
    "/{year}/{month}/published",
    response_model=SchedulePublishedRead,
    tags=["schedules:doctor"],
    summary="Read current PUBLISHED schedule for the period (pointer-based)",
)
def schedules_published_read(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    user: UserCtx = Depends(require_doctor),
) -> SchedulePublishedRead:
    """
    Return the currently published snapshot for the period (404 if missing).
    """
    try:
        return svc.get_published(year, month)
    except ValueError as e:
        _raise(e)
        assert False


# ---------------------- DOCTOR: my assignments (placeholder) -------------------
@router.get(
    "/{year}/{month}/my-assignments",
    response_model=MyAssignmentsRead,
    tags=["schedules:doctor"],
    summary="List my assignments from the current PUBLISHED schedule (TODO)",
)
def schedules_my_assignments(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    user: UserCtx = Depends(require_doctor),
) -> MyAssignmentsRead:
    """
    Placeholder for per-doctor assignment view (will filter from published payload).
    """
    return MyAssignmentsRead(doctor_id=user.user_id if user else -1, year=year, month=month, assignments=[])
