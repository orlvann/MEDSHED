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
# - "period_closed"                         -> 403
# - "edit_conflict"                          -> 409
# - "cannot_undo" / "cannot_redo"            -> 409
# - "publish_blocked_by_hard_rules"          -> 409
# - "invalid_accepted_exception"             -> 400
# - "invalid_head_commitment_resolution"     -> 400
# - "not_found"                              -> 404
# - "generate_requires_ignore"               -> 409   (FE uses .context.issues_* to propose ignores)
# - "generate_requires_head_resolution"      -> 409   (FE shows modal to pick a head per conflicting slot)
# - "generate_infeasible"                    -> 409   (FE shows solver_status + issues_sample from .context)
# - "db_integrity_error"                     -> 500   (unexpected; indicates a bug)
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

    Rules:
    - Map known codes to HTTP status.
    - Always include `context` in the response (at least {}), so FE never loses data.
    - Optionally override `detail` with a short human-friendly message (code stays stable).
    """
    code = str(e)

    mapping = {
        "period_closed": status.HTTP_403_FORBIDDEN,
        "edit_conflict": status.HTTP_409_CONFLICT,
        "cannot_undo": status.HTTP_409_CONFLICT,
        "cannot_redo": status.HTTP_409_CONFLICT,
        "publish_blocked_by_hard_rules": status.HTTP_409_CONFLICT,
        "invalid_accepted_exception": status.HTTP_400_BAD_REQUEST,
        "invalid_head_commitment_resolution": status.HTTP_400_BAD_REQUEST,
        "not_found": status.HTTP_404_NOT_FOUND,
        # generate gatekeeper errors
        "generate_requires_ignore": status.HTTP_409_CONFLICT,
        "generate_requires_head_resolution": status.HTTP_409_CONFLICT,
        "generate_infeasible": status.HTTP_409_CONFLICT,
        # DB integrity fallback (see SchedulingService._translate_sqla_errors)
        "db_integrity_error": status.HTTP_500_INTERNAL_SERVER_ERROR,
        "db_error": status.HTTP_500_INTERNAL_SERVER_ERROR,
    }

    # Short, human-friendly descriptions (optional cosmetic layer).
    human_detail = {
        "generate_requires_ignore": "Generation requires ignore_days/ignore_slots to proceed.",
        "generate_requires_head_resolution": "Generation requires choosing a head for conflicting commitment slots.",
        "generate_infeasible": "Generation failed: solver could not find a feasible solution.",
        "invalid_head_commitment_resolution": "Invalid head commitment resolution payload.",
        "db_integrity_error": "Database integrity error.",
        "db_error": "Database error.",
        "publish_blocked_by_hard_rules": "Publishing blocked: hard rule violations detected.",
    }

    if code in mapping:
        # Always return a dict for context (never None), so FE can rely on it.
        context = getattr(e, "context", None) or {}

        # Prefer explicit human-friendly detail; otherwise keep any attached detail; fallback to code.
        detail = human_detail.get(code) or getattr(e, "detail", None) or code

        raise HTTPException(
            status_code=mapping[code],
            detail=make_error(code, context=context, detail=detail),
        )

    raise e


# ------------------------------- ADMIN: generate -------------------------------
@router.post(
    "/generate",
    status_code=status.HTTP_201_CREATED,
    response_model=ScheduleGenerateCreated,
    tags=["schedules:admin"],
    summary="Generate schedule: writes working + creates first draft checkpoint",
    responses={
        201: {
            "description": "Working saved + first draft checkpoint created + diagnostics returned.",
            "content": {
                "application/json": {
                    "example": {
                        "year": 2026,
                        "month": 2,
                        "status": "draft",
                        "working": {
                            "year": 2026,
                            "month": 2,
                            "exists": True,
                            "participant_doctor_ids": [101, 102, 103],
                            "assignments": [
                                {"day": 1, "shift_type": "onsite", "doctor_id": 101},
                                {"day": 1, "shift_type": "oncall", "doctor_id": 102},
                            ],
                            "meta": {"labels": ["as_generated"], "exceptions": [], "solver_status": "OK"},
                            "updated_at": "2026-01-28T09:15:00Z",
                            "lock_version": 2,
                            "inputs_snapshot": {
                                "doctors": {
                                    "101": {
                                        "role": "specialist",
                                        "is_head": True,
                                        "display_name": "Jan Kowalski",
                                        "is_active_at_snapshot": True,
                                    }
                                },
                                "preference_version_id_by_doctor": {"101": 55, "102": 56, "103": None},
                            },
                        },
                        "draft": {
                            "version_id": "123",
                            "checkpoints_count": 1,
                            "can_undo": False,
                            "can_redo": False,
                            "payload": {
                                "participant_doctor_ids": [101, 102, 103],
                                "assignments": [
                                    {"day": 1, "shift_type": "onsite", "doctor_id": 101},
                                    {"day": 1, "shift_type": "oncall", "doctor_id": 102},
                                ],
                                "inputs_snapshot": {
                                    "doctors": {
                                        "101": {
                                            "role": "specialist",
                                            "is_head": True,
                                            "display_name": "Jan Kowalski",
                                            "is_active_at_snapshot": True,
                                        }
                                    },
                                    "preference_version_id_by_doctor": {"101": 55, "102": 56, "103": None},
                                },
                                "meta": {"labels": ["as_generated"], "exceptions": [], "solver_status": "OK"},
                            },
                        },
                        "diagnostics": {
                            "version_id": "123",
                            "computed_at": "2026-01-28T09:15:01Z",
                            "summary": {"score_total": 0.83, "coverage_gaps_total": 0, "hard_violations_total": 0},
                            "details": {},
                        },
                    }
                }
            },
        },
        409: {
            "description": "Generation blocked or infeasible.",
            "content": {
                "application/json": {
                    "examples": {
                        "requires_ignore_days_or_slots": {
                            "summary": "Feasibility pre-check: requires ignore_days/ignore_slots",
                            "value": {
                                "code": "generate_requires_ignore",
                                "detail": "Generation requires ignore_days/ignore_slots to proceed.",
                                "context": {
                                    "year": 2026,
                                    "month": 2,
                                    "issues_total": 2,
                                    "issues_truncated": False,
                                    "issues_summary": [
                                        {"code": "no_specialist", "count": 1},
                                        {"code": "no_onsite_candidate", "count": 1},
                                    ],
                                    "issues_sample": [
                                        {
                                            "day": 3,
                                            "code": "no_specialist",
                                            "message": "No specialist is available on this day.",
                                        },
                                        {
                                            "day": 3,
                                            "code": "no_onsite_candidate",
                                            "message": "No doctor is available for onsite duty on this day.",
                                        },
                                    ],
                                },
                            },
                        },
                        "infeasible_head_commitments_or_solver": {
                            "summary": "Head commitments invalid or CP-SAT infeasible",
                            "value": {
                                "code": "generate_infeasible",
                                "detail": "Generation failed: solver could not find a feasible solution.",
                                "context": {
                                    "year": 2026,
                                    "month": 2,
                                    "solver_status": "INFEASIBLE",
                                    "issues_total": 1,
                                    "issues_truncated": False,
                                    "issues_summary": [{"code": "head_commitment_conflict", "count": 1}],
                                    "issues_sample": [
                                        {
                                            "day": 5,
                                            "code": "head_commitment_conflict",
                                            "message": "Multiple heads have a commitment for the same slot. "
                                            "(shift=onsite, head_id=101, other_head_id=102)",
                                        }
                                    ],
                                },
                            },
                        },
                    }
                }
            },
        },
    },
)
def generate_schedule(
    body: ScheduleGenerateRequest = Body(...),
    user: UserCtx = Depends(require_admin),
) -> ScheduleGenerateCreated:
    """
    Generate a new schedule for {year, month}.

    Possible blocking outcomes (409) returned as a structured error:
    - generate_requires_ignore:
        context contains issues_* describing which days/slots have no feasible coverage.
        FE should propose ignore_days/ignore_slots based on issues_sample.
    - generate_requires_head_resolution:
        context.head_commitment_conflicts contains conflicting slots and head_candidates.
        FE should show a modal and resend the request with head_commitment_resolutions[].
    - generate_infeasible:
        solver ran but returned non-OK status; context.solver_status + issues_sample help explain why.
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
    summary="Get diagnostics for working, draft, or published schedule",
    operation_id="schedules_diagnostics_get",
    responses={
        200: {
            "description": "Diagnostics computed (and cached for draft/published).",
            "content": {
                "application/json": {
                    "examples": {
                        "working": {
                            "summary": "Working diagnostics (includes working_lock_version)",
                            "value": {
                                "version_id": "working",
                                "computed_at": "2026-01-28T09:20:00Z",
                                "summary": {"score_total": 0.74, "coverage_gaps_total": 2, "hard_violations_total": 0},
                                "details": {"working_lock_version": 7},
                            },
                        },
                        "draft": {
                            "summary": "Draft diagnostics (version_id from pointer)",
                            "value": {
                                "version_id": "123",
                                "computed_at": "2026-01-28T09:15:01Z",
                                "summary": {"score_total": 0.83, "coverage_gaps_total": 0, "hard_violations_total": 0},
                                "details": {},
                            },
                        },
                    }
                }
            },
        },
        404: {
            "description": "Not found (no working row or pointer/version missing).",
        },
    },
)
def schedules_diagnostics(
    user: UserCtx = Depends(require_admin),  # RBAC: admin only (dopasuj do swojej polityki)
    year: int = Path(..., ge=1900, le=2100, description="Calendar year"),
    month: int = Path(..., ge=1, le=12, description="Month 1..12"),
    target: Literal["working", "draft", "published"] = Query(
        ...,
        description=(
            "Which schedule source to analyze: "
            "'working' = live autosave buffer (includes details.working_lock_version), "
            "'draft' = current draft pointer, "
            "'published' = current published pointer."
        ),
    ),
) -> DiagnosticsRead:
    """
    Admin diagnostics endpoint.

    Important behavior:
    - target='working' reads the LIVE working buffer (autosave). It returns
      details.working_lock_version so the frontend can keep it and later use it
      for optimistic concurrency / “publish what I see” confirmation (ACK).
    - target='draft' or 'published' resolves the pointer to a version_id and returns
      diagnostics for that immutable version (computed and cached).

    The router is thin: it delegates pointer resolution and diagnostics computation
    to SchedulingService.
    """
    try:
        return svc.get_diagnostics(year=year, month=month, target=target)
    except ValueError as e:
        _raise(e)
        assert False


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
    summary="List my assignments from the current PUBLISHED schedule",
)
def schedules_my_assignments(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    user: UserCtx = Depends(require_doctor),
) -> MyAssignmentsRead:
    """
    Doctor endpoint: return ONLY my assignments for the period.

    Rules:
    - Source of truth is the current PUBLISHED pointer (stable doctor view).
    - Doctor id is taken from auth context (user.user_id in MVP).
    """
    try:
        return svc.get_my_assignments(year=year, month=month, doctor_id=user.user_id if user else -1)
    except ValueError as e:
        _raise(e)
        assert False
