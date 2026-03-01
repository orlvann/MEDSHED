# backend/routers/schedules.py
"""
Schedules router — thin I/O layer.

This router:
- validates I/O shapes (Pydantic schemas),
- performs RBAC (admin/doctor),
- maps domain ValueError codes -> HTTP errors,
- delegates ALL business logic and DB access to SchedulingService.

OpenAPI examples are kept consistent with DTOs in:
- backend/models/schemas/schedule.py
- backend/models/schemas/diagnostics.py

IMPORTANT ABOUT DIAGNOSTICS DTO:
- DiagnosticsRead.details is a typed structure (findings/per_doctor/rankings/audit/solver_components_total).
- Slot ignores (COVERAGE_IGNORED_SLOT) are NOT emitted as findings anymore.
  They only mark matching coverage gaps with context.was_ignored=True.
- Human decisions are exposed via details.audit[] (extracted from payload.meta.exceptions).
  We support TWO audit shapes:
  1) slot-level markers (MUST include day + shift_type) used to mark coverage gaps as was_ignored=True,
  2) action-level decisions/justifications (may omit day/shift_type) that explain "why" an admin
     chose to proceed (e.g. ignore slots before generation, force publish acceptances).
  FE should offer justification fields as OPTIONAL.

IMPORTANT ABOUT ERROR SHAPE:
- Runtime returns FastAPI HTTPException with detail=make_error(...).
  Response body shape is always: {"detail": {"code": str, "detail": str, "context": dict}}
"""

from __future__ import annotations

from io import BytesIO
from typing import Literal, Optional, cast
from typing import Literal as LiteralType

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status
from fastapi.responses import StreamingResponse

from backend.core import issues
from backend.models.schemas.diagnostics import DiagnosticsRead, MyDoctorDiagnosticsRead
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
from backend.services.errors import DomainError
from backend.services.export_service import ExportService
from backend.services.export_service import ExportService as _CalExportService

router = APIRouter(prefix="/api/v1/schedules")
svc = SchedulingService()


def _issue_code(v: object) -> str:
    """
    Convert issue enum/constant to a stable string code for JSON/OpenAPI examples.
    """
    return str(getattr(v, "value", v))


def _err_example(code: str, *, detail: str | None = None, context: dict | None = None) -> dict:
    """
    Helper for OpenAPI examples.

    Runtime always returns: {"detail": {code, detail, context}}
    and context is always a dict (never None).
    """
    safe_context = context if isinstance(context, dict) else {}
    return {"detail": make_error(code, detail=detail, context=safe_context)}


def _raise(e: ValueError) -> None:
    """
    Convert ValueError(code) from service -> HTTPException with a stable error payload.
    """
    # DomainError may carry richer fields:
    # - code: stable error code for FE
    # - context: machine-readable payload (dict)
    # - detail: optional human-friendly detail string
    #
    # For plain ValueError("code"), str(e) is the code.
    code = str(getattr(e, "code", str(e)))

    mapping = {
        "period_closed": status.HTTP_403_FORBIDDEN,
        "edit_conflict": status.HTTP_409_CONFLICT,
        "working_requires_snapshot": status.HTTP_409_CONFLICT,
        "cannot_undo": status.HTTP_409_CONFLICT,
        "cannot_redo": status.HTTP_409_CONFLICT,
        "publish_blocked_by_hard_rules": status.HTTP_409_CONFLICT,
        "invalid_accepted_exception": status.HTTP_400_BAD_REQUEST,
        "invalid_head_commitment_resolution": status.HTTP_400_BAD_REQUEST,
        "not_found": status.HTTP_404_NOT_FOUND,
        "generate_requires_ignore": status.HTTP_409_CONFLICT,
        "diagnostics_requires_snapshot": status.HTTP_409_CONFLICT,
        "publish_requires_snapshot": status.HTTP_409_CONFLICT,
        "generate_requires_head_resolution": status.HTTP_409_CONFLICT,
        "generate_infeasible": status.HTTP_409_CONFLICT,
        "db_integrity_error": status.HTTP_500_INTERNAL_SERVER_ERROR,
        "db_error": status.HTTP_500_INTERNAL_SERVER_ERROR,
    }

    human_detail = {
        "generate_requires_ignore": "Not enough availability to generate. Choose days to ignore and try again.",
        "generate_requires_head_resolution": "Two heads chose the same duty. Pick who gets it and try again.",
        "generate_infeasible": "Generation failed: solver could not find a feasible solution. Change inputs "
        "(availability / limits) and try again.",
        "invalid_head_commitment_resolution": "Invalid head commitment resolution payload.",
        "publish_blocked_by_hard_rules": "Publishing blocked: hard rule violations detected. "
        "Fix them or use Force Publish.",
        "diagnostics_requires_snapshot": "Cannot compute diagnostics. Regenerate the schedule.",
        "publish_requires_snapshot": "Cannot publish. Regenerate the schedule first.",
        "working_requires_snapshot": "Cannot save or analyze this draft. Regenerate the schedule.",
        "db_integrity_error": "Server error while saving. Try again.",
        "db_error": "Server error. Try again.",
    }

    if code in mapping:
        context = getattr(e, "context", None)
        if not isinstance(context, dict):
            context = {}

        # Prefer DomainError.detail if present; otherwise fallback to router's generic text.
        detail = getattr(e, "detail", None) or human_detail.get(code) or code

        raise HTTPException(
            status_code=mapping[code],
            detail=make_error(code, detail=detail, context=context),
        )

    raise e


# ------------------------------- ADMIN: generate -------------------------------
_OPENAPI_EXAMPLES_WORKING_PUT_REQUEST = {
    "autosave_minimal": {
        "summary": "Autosave (replace assignments; meta omitted)",
        "value": {
            "assignments": [
                {"day": 1, "shift_type": "onsite", "doctor_id": 101},
                {"day": 1, "shift_type": "oncall", "doctor_id": 102},
            ],
            "meta": None,
            "if_match_lock_version": 8,
        },
    },
    "autosave_with_labels": {
        "summary": "Autosave with meta.labels",
        "value": {
            "assignments": [
                {"day": 2, "shift_type": "onsite", "doctor_id": 101},
                {"day": 2, "shift_type": "oncall", "doctor_id": 103},
            ],
            "meta": {"labels": ["edited_by_admin"]},
            "if_match_lock_version": 8,
        },
    },
    "autosave_clear_all": {
        "summary": "Clear all assignments (empty grid)",
        "value": {"assignments": [], "meta": None, "if_match_lock_version": 8},
    },
    "autosave_without_occ": {
        "summary": "Autosave without OCC (if_match_lock_version omitted → last write wins)",
        "value": {
            "assignments": [{"day": 3, "shift_type": "onsite", "doctor_id": 101}],
            "meta": None,
            "if_match_lock_version": None,
        },
    },
}

_OPENAPI_EXAMPLES_CHECKPOINT_REQUEST = {
    "no_body": {"summary": "No request body (defaults apply)", "value": None},
    "with_note": {
        "summary": "Checkpoint with a note (admin-only draft history)",
        "value": {"note": "Manual adjustments after solver run."},
    },
}


_OPENAPI_EXAMPLES_PUBLISH_REQUEST = {
    "normal": {
        "summary": "Publish (no force)",
        "value": {"force": False, "note": "Finalize", "accepted_exceptions": []},
    },
    "force_with_action_justification": {
        "summary": "Force publish (accept ALL blockers) + audit justification",
        "value": {
            "force": True,
            "note": "Emergency publish (sorry, but we have staffing shortage this month guys...)",
            "accepted_exceptions": [
                {
                    "code": _issue_code(issues.COVERAGE_MISSING_REQUIRED_SLOT),
                    "justification": "Emergency staffing shortage; publishing despite known gaps.",
                }
            ],
        },
    },
}


def _example_categories() -> dict:
    # Minimal valid DoctorCategoriesRead (typed, stable keys)
    return {
        "rest": {"applicable": True, "badness": 0.0, "stars": 5},
        "preferred_days": {"applicable": True, "badness": 0.2, "stars": 4, "requested": 2, "missed": 0},
        "fairness": {"applicable": True, "badness": 0.3, "stars": 4},
        "totals": {"applicable": True, "badness": 0.4, "stars": 4},
        "weekday_patterns": {
            "applicable": False,
            "badness": 0.0,
            "stars": None,
            "avoid_penalty": 0,
            "preferred_bonus": 0,
            "preferred_declared": False,
            "avoid_declared": False,
        },
        "friday_free_weekend": {"applicable": False, "badness": 0.0, "stars": None},
        "preferred_partners": {"applicable": False, "badness": 0.0, "stars": None},
    }


def _example_solver_components_by_doc() -> dict:
    return {
        "rest_penalty": 0,
        "preferred_days_penalty": 10,
        "totals_penalty": 0,
        "fairness_penalty": 0,
        "weekday_patterns_penalty": 0,
        "weekday_patterns_bonus": 0,
        "friday_free_weekend_penalty": 0,
        "preferred_partners_bonus": 0.0,
    }


@router.post(
    "/generate",
    status_code=status.HTTP_201_CREATED,
    response_model=ScheduleGenerateCreated,
    tags=["schedules:admin"],
    summary="Generate schedule (creates working draft, first checkpoint and diagnostics)",
    description=(
        "Generate a monthly duty schedule for the selected participants.\n\n"
        "Flow:\n"
        "1) Build input data from DB + request.\n"
        "2) Gatekeeper: feasibility precheck (blocks with 409 generate_requires_ignore).\n"
        "3) Gatekeeper: head commitment conflicts (blocks with 409 generate_requires_head_resolution).\n"
        "4) Run solver (blocks with 409 generate_infeasible if solver status != OK).\n"
        "5) On success: save working payload, create first draft checkpoint, compute diagnostics.\n\n"
        "Important:\n"
        "- ignore_slots is slot-only (day + shift_type). There is no ignore_days.\n"
        "  To ignore a whole day, send BOTH slots: onsite + oncall for that day.\n"
        "- head_commitment_resolutions are applied only for this generation run (not persisted to DB preferences)."
    ),
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
                            "meta": {
                                "labels": ["as_generated"],
                                "solver_status": "OK",
                                "exceptions": [
                                    {
                                        "kind": "generation_ignore",
                                        "code": "coverage_ignored_slot",
                                        "day": 3,
                                        "shift_type": "onsite",
                                        "accepted_at": "2026-01-28T09:15:00Z",
                                        "accepted_by_user_id": 1,
                                    },
                                    {
                                        "kind": "generation_ignore",
                                        "code": "generation_ignore",
                                        "justification": "Accept coverage gaps for these slots "
                                        "due to known staffing shortage.",
                                        "accepted_at": "2026-01-28T09:15:00Z",
                                        "accepted_by_user_id": 1,
                                    },
                                    {
                                        "kind": "head_commitment_resolution",
                                        "code": "head_commitment_resolution",
                                        "day": 5,
                                        "shift_type": "onsite",
                                        "chosen_head_id": 101,
                                        "accepted_at": "2026-01-28T09:15:00Z",
                                        "accepted_by_user_id": 1,
                                    },
                                ],
                            },
                            "updated_at": "2026-01-28T09:15:00Z",
                            "lock_version": 2,
                            "inputs_snapshot": {
                                "doctors": {
                                    "101": {
                                        "role": "specialist",
                                        "is_head": True,
                                        "display_name": "Jan Kowalski",
                                        "is_active_at_snapshot": True,
                                    },
                                    "102": {
                                        "role": "resident",
                                        "is_head": False,
                                        "display_name": "Doctor 102",
                                        "is_active_at_snapshot": True,
                                    },
                                    "103": {
                                        "role": "resident",
                                        "is_head": False,
                                        "display_name": "Doctor 103",
                                        "is_active_at_snapshot": True,
                                    },
                                },
                                "preference_version_id_by_doctor": {"101": 55, "102": 56, "103": None},
                            },
                        },
                        "draft": {
                            "version_id": 123,
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
                                        },
                                        "102": {
                                            "role": "resident",
                                            "is_head": False,
                                            "display_name": "Doctor 102",
                                            "is_active_at_snapshot": True,
                                        },
                                        "103": {
                                            "role": "resident",
                                            "is_head": False,
                                            "display_name": "Doctor 103",
                                            "is_active_at_snapshot": True,
                                        },
                                    },
                                    "preference_version_id_by_doctor": {"101": 55, "102": 56, "103": None},
                                },
                                "meta": {
                                    "labels": ["as_generated"],
                                    "solver_status": "OK",
                                    "exceptions": [
                                        {
                                            "kind": "generation_ignore",
                                            "code": "coverage_ignored_slot",
                                            "day": 3,
                                            "shift_type": "onsite",
                                            "accepted_at": "2026-01-28T09:15:00Z",
                                            "accepted_by_user_id": 1,
                                        },
                                        {
                                            "kind": "generation_ignore",
                                            "code": "generation_ignore",
                                            "justification": "Accept coverage gaps for these slots "
                                            "due to known staffing shortage.",
                                            "accepted_at": "2026-01-28T09:15:00Z",
                                            "accepted_by_user_id": 1,
                                        },
                                        {
                                            "kind": "head_commitment_resolution",
                                            "code": "head_commitment_resolution",
                                            "day": 5,
                                            "shift_type": "onsite",
                                            "chosen_head_id": 101,
                                            "accepted_at": "2026-01-28T09:15:00Z",
                                            "accepted_by_user_id": 1,
                                        },
                                    ],
                                },
                            },
                        },
                        "diagnostics": {
                            "version_id": 123,
                            "computed_at": "2026-01-28T09:15:01Z",
                            "summary": {
                                "coverage_missing_required_slots": 0,
                                "hard_issues_count": 0,
                                "rest_violations": 0,
                                "fairness_index": 1.0,
                                "preference_fulfillment_pct": 100.0,
                            },
                            "details": {
                                "findings": [],
                                "per_doctor": [
                                    {
                                        "doctor_id": 101,
                                        "display_name": "Jan Kowalski",
                                        "assigned_onsite_total": 0,
                                        "assigned_oncall_total": 0,
                                        "rest_violations": 0,
                                        "preferred_days_requested": 0,
                                        "preferred_days_missed": 0,
                                        "preference_fulfillment_pct": 100.0,
                                        "ui_stars": 5,
                                        "ui_reasons_codes": ["preferences_met", "good_rest"],
                                        "categories": _example_categories(),
                                        "solver_components_by_doc": _example_solver_components_by_doc(),
                                    }
                                ],
                                "rankings": {
                                    "unhappy": [],
                                    "happy": [
                                        {
                                            "doctor_id": 101,
                                            "score": 5,
                                            "reasons_codes": ["preferences_met", "good_rest"],
                                        }
                                    ],
                                },
                                "audit": [],
                                "solver_components_total": {},
                                "working_lock_version": None,
                            },
                        },
                    }
                }
            },
        },
        400: {
            "description": "Invalid request payload (e.g., invalid head commitment resolution).",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_head_commitment_resolution": {
                            "summary": "Chosen head is not a valid head/participant for that conflict slot.",
                            "value": _err_example(
                                "invalid_head_commitment_resolution",
                                detail="Invalid head commitment resolution payload.",
                                context={},
                            ),
                        }
                    }
                }
            },
        },
        409: {
            "description": "Generation blocked (precheck) or infeasible (solver).",
            "content": {
                "application/json": {
                    "examples": {
                        "generate_requires_ignore": {
                            "summary": "Feasibility precheck found issues; "
                            "FE must retry with ignore_slots or change inputs.",
                            "value": _err_example(
                                "generate_requires_ignore",
                                detail="Not enough availability to generate. Choose days to ignore and try again.",
                                context={
                                    "year": 2026,
                                    "month": 2,
                                    "issues_total": 1,
                                    "issues_truncated": False,
                                    "issues_summary": [
                                        {"code": "no_specialist", "count": 1},
                                    ],
                                    "issues_sample": [
                                        {
                                            "day": 24,
                                            "code": "no_specialist",
                                            "message": "No specialist is available on this day.",
                                        }
                                    ],
                                    "suggested_ignored_slots": [
                                        {"day": 24, "shift_type": "onsite"},
                                    ],
                                    "suggested_ignore_reason_codes": [
                                        "no_specialist",
                                    ],
                                },
                            ),
                        },
                        "generate_requires_head_resolution": {
                            "summary": "Multiple heads want the same slot; "
                            "FE must collect head_commitment_resolutions and retry.",
                            "value": _err_example(
                                "generate_requires_head_resolution",
                                detail="Two heads chose the same duty. Pick who gets it and try again.",
                                context={
                                    "year": 2026,
                                    "month": 2,
                                    "head_commitment_conflicts": [
                                        {
                                            "day": 5,
                                            "shift_type": "onsite",
                                            "head_candidates": [
                                                {"doctor_id": 101, "display_name": "Jan Kowalski"},
                                                {"doctor_id": 102, "display_name": "Anna Nowak"},
                                            ],
                                        }
                                    ],
                                },
                            ),
                        },
                        "generate_infeasible": {
                            "summary": "Solver ran but could not find a feasible solution (status != OK).",
                            "value": _err_example(
                                "generate_infeasible",
                                detail="Generation failed: solver could not find a feasible solution. "
                                "Change inputs (availability / limits) and try again.",
                                context={
                                    "year": 2026,
                                    "month": 2,
                                    "solver_status": "INFEASIBLE",
                                    "issues_total": 2,
                                    "issues_truncated": False,
                                    "issues_summary": [{"code": "no_specialist", "count": 2}],
                                    "issues_sample": [
                                        {"day": 12, "code": "no_specialist", "message": "no_specialist"},
                                        {"day": 13, "code": "no_specialist", "message": "no_specialist"},
                                    ],
                                },
                            ),
                        },
                    }
                }
            },
        },
        500: {
            "description": "Unexpected DB error.",
            "content": {
                "application/json": {
                    "examples": {
                        "db_error": {
                            "summary": "Generic server-side DB failure.",
                            "value": _err_example("db_error", detail="Server error. Try again.", context={}),
                        }
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
    """
    try:
        return svc.generate(body, user_id=user.user_id if user else None)
    except ValueError as e:
        _raise(e)
        assert False


# ---------------------- DOCTOR: calendar subscription token ------
# IMPORTANT: these /me/* routes MUST be registered before any /{year}/{month}
# routes, otherwise FastAPI tries to parse "me" as an integer and returns 422.


_cal_export_svc = _CalExportService()


@router.get(
    "/me/calendar-token",
    tags=["schedules:doctor"],
    summary="Get or create my calendar subscription token",
    responses={
        200: {
            "description": "Calendar feed token.",
            "content": {"application/json": {"example": {"token": "550e8400-e29b-41d4-a716-446655440000"}}},
        },
        403: {"description": "Forbidden (not a doctor account)."},
    },
)
def get_calendar_token(
    user: UserCtx = Depends(require_doctor),
):
    if user.doctor_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=make_error("forbidden"))
    try:
        token = _cal_export_svc.get_or_create_calendar_token(int(user.doctor_id))
        return {"token": token}
    except ValueError as e:
        _raise(e)
        assert False


@router.post(
    "/me/calendar-token/regenerate",
    tags=["schedules:doctor"],
    summary="Regenerate my calendar subscription token (invalidates old URL)",
    responses={
        200: {
            "description": "New calendar feed token.",
            "content": {"application/json": {"example": {"token": "550e8400-e29b-41d4-a716-446655440000"}}},
        },
        403: {"description": "Forbidden (not a doctor account)."},
    },
)
def regenerate_calendar_token(
    user: UserCtx = Depends(require_doctor),
):
    if user.doctor_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=make_error("forbidden"))
    try:
        token = _cal_export_svc.regenerate_calendar_token(int(user.doctor_id))
        return {"token": token}
    except ValueError as e:
        _raise(e)
        assert False


# --------------------------- ADMIN: diagnostics --------------------------


@router.get(
    "/{year}/{month}/diagnostics",
    response_model=DiagnosticsRead,
    tags=["schedules:admin"],
    summary="Get diagnostics for working, draft, or published schedule",
    operation_id="schedules_diagnostics_get",
    description=(
        "Return schedule diagnostics (KPIs + details) for {year, month}.\n\n"
        "Use query param target:\n"
        "- working: analyze the current working buffer (live edits)\n"
        "- draft: analyze the current draft checkpoint (pointer -> version)\n"
        "- published: analyze the current published version (pointer -> version)\n\n"
        "DTO notes (stable contract):\n"
        "- details.rankings uses keys: happy and unhappy (full lists).\n"
        "- DoctorRankingItemRead.score is the UI stars (1..5).\n"
        "- details.per_doctor items include categories and solver_components_by_doc.\n"
        "Important rules:\n"
        "- inputs_snapshot is required (NO FALLBACKS). If missing -> 409.\n"
        "- working is computed live (version_id=null).\n"
        "- draft/published are computed per version_id and cached in ScheduleDiagnostics.\n"
        "- Gaps are always critical; if previously accepted as ignore, a gap still stays a gap "
        "(context.was_ignored=true).\n"
    ),
    responses={
        200: {
            "description": "Diagnostics computed (and cached for draft/published).",
            "content": {
                "application/json": {
                    "examples": {
                        "working": {
                            "summary": "Working diagnostics (computed live; details includes working_lock_version).",
                            "value": {
                                "version_id": None,
                                "computed_at": "2026-01-28T09:20:00Z",
                                "summary": {
                                    "coverage_missing_required_slots": 2,
                                    "hard_issues_count": 2,
                                    "rest_violations": 0,
                                    "fairness_index": 0.93,
                                    "preference_fulfillment_pct": 78.0,
                                },
                                "details": {
                                    "findings": [
                                        {
                                            "code": _issue_code(issues.COVERAGE_MISSING_REQUIRED_SLOT),
                                            "severity": "critical",
                                            "context": {"day": 2, "shift_type": "onsite", "was_ignored": True},
                                        }
                                    ],
                                    "per_doctor": [
                                        {
                                            "doctor_id": 101,
                                            "display_name": "Doctor 101",
                                            "assigned_onsite_total": 5,
                                            "assigned_oncall_total": 3,
                                            "rest_violations": 0,
                                            "preferred_days_requested": 2,
                                            "preferred_days_missed": 1,
                                            "preference_fulfillment_pct": 78.0,
                                            "ui_stars": 3,
                                            "ui_reasons_codes": ["preferred_days_missed", "preferences_not_fully_met"],
                                            "categories": _example_categories(),
                                            "solver_components_by_doc": _example_solver_components_by_doc(),
                                        }
                                    ],
                                    "rankings": {
                                        "unhappy": [
                                            {"doctor_id": 101, "score": 3, "reasons_codes": ["preferred_days_missed"]}
                                        ],
                                        "happy": [],
                                    },
                                    "audit": [
                                        {
                                            "kind": "generation_ignore",
                                            "code": _issue_code(issues.COVERAGE_IGNORED_SLOT),
                                            "day": 2,
                                            "shift_type": "onsite",
                                            "justification": "Holiday staffing shortage — generating draft with gaps.",
                                            "accepted_by_user_id": 1,
                                            "accepted_at": "2026-01-28T09:10:00Z",
                                        }
                                    ],
                                    "solver_components_total": {
                                        "rest_penalty": 0,
                                        "preferred_days_penalty": 30,
                                        "totals_penalty": 40,
                                        "fairness_penalty": 10,
                                        "weekday_patterns_penalty": 0,
                                        "weekday_patterns_bonus": 0,
                                        "friday_free_weekend_penalty": 0,
                                        "preferred_partners_bonus": 0.0,
                                    },
                                    "working_lock_version": 7,
                                },
                            },
                        },
                        "draft": {
                            "summary": "Draft diagnostics (version_id is current draft checkpoint id).",
                            "value": {
                                "version_id": 123,
                                "computed_at": "2026-01-28T09:15:01Z",
                                "summary": {
                                    "coverage_missing_required_slots": 0,
                                    "hard_issues_count": 0,
                                    "rest_violations": 0,
                                    "fairness_index": 1.0,
                                    "preference_fulfillment_pct": 100.0,
                                },
                                "details": {
                                    "findings": [
                                        {
                                            "code": _issue_code(issues.COVERAGE_MISSING_REQUIRED_SLOT),
                                            "severity": "critical",
                                            "context": {"day": 2, "shift_type": "onsite", "was_ignored": True},
                                        }
                                    ],
                                    "per_doctor": [
                                        {
                                            "doctor_id": 101,
                                            "display_name": "Doctor 101",
                                            "assigned_onsite_total": 5,
                                            "assigned_oncall_total": 3,
                                            "rest_violations": 0,
                                            "preferred_days_requested": 2,
                                            "preferred_days_missed": 1,
                                            "preference_fulfillment_pct": 78.0,
                                            "ui_stars": 3,
                                            "ui_reasons_codes": ["preferred_days_missed", "preferences_not_fully_met"],
                                            "categories": _example_categories(),
                                            "solver_components_by_doc": _example_solver_components_by_doc(),
                                        }
                                    ],
                                    "rankings": {
                                        "unhappy": [
                                            {"doctor_id": 101, "score": 3, "reasons_codes": ["preferred_days_missed"]}
                                        ],
                                        "happy": [],
                                    },
                                    "audit": [
                                        {
                                            "kind": "generation_ignore",
                                            "code": _issue_code(issues.COVERAGE_IGNORED_SLOT),
                                            "day": 2,
                                            "shift_type": "onsite",
                                            "justification": "Holiday staffing shortage — generating draft with gaps.",
                                            "accepted_by_user_id": 1,
                                            "accepted_at": "2026-01-28T09:10:00Z",
                                        }
                                    ],
                                    "solver_components_total": {
                                        "rest_penalty": 0,
                                        "preferred_days_penalty": 30,
                                        "totals_penalty": 40,
                                        "fairness_penalty": 10,
                                        "weekday_patterns_penalty": 0,
                                        "weekday_patterns_bonus": 0,
                                        "friday_free_weekend_penalty": 0,
                                        "preferred_partners_bonus": 0.0,
                                    },
                                    "working_lock_version": 7,
                                },
                            },
                        },
                        "published": {
                            "summary": "Published diagnostics (version_id is current published version id).",
                            "value": {
                                "version_id": 200,
                                "computed_at": "2026-01-28T10:05:01Z",
                                "summary": {
                                    "coverage_missing_required_slots": 1,
                                    "hard_issues_count": 1,
                                    "rest_violations": 0,
                                    "fairness_index": 0.95,
                                    "preference_fulfillment_pct": 82.0,
                                },
                                "details": {
                                    "findings": [
                                        {
                                            "code": _issue_code(issues.COVERAGE_MISSING_REQUIRED_SLOT),
                                            "severity": "critical",
                                            "context": {"day": 2, "shift_type": "onsite", "was_ignored": True},
                                        }
                                    ],
                                    "per_doctor": [
                                        {
                                            "doctor_id": 101,
                                            "display_name": "Doctor 101",
                                            "assigned_onsite_total": 5,
                                            "assigned_oncall_total": 3,
                                            "rest_violations": 0,
                                            "preferred_days_requested": 2,
                                            "preferred_days_missed": 1,
                                            "preference_fulfillment_pct": 78.0,
                                            "ui_stars": 3,
                                            "ui_reasons_codes": ["preferred_days_missed", "preferences_not_fully_met"],
                                            "categories": _example_categories(),
                                            "solver_components_by_doc": _example_solver_components_by_doc(),
                                        }
                                    ],
                                    "rankings": {
                                        "unhappy": [
                                            {"doctor_id": 101, "score": 3, "reasons_codes": ["preferred_days_missed"]}
                                        ],
                                        "happy": [],
                                    },
                                    "audit": [
                                        {
                                            "kind": "generation_ignore",
                                            "code": _issue_code(issues.COVERAGE_IGNORED_SLOT),
                                            "day": 2,
                                            "shift_type": "onsite",
                                            "justification": "Holiday staffing shortage — generating draft with gaps.",
                                            "accepted_by_user_id": 1,
                                            "accepted_at": "2026-01-28T09:10:00Z",
                                        }
                                    ],
                                    "solver_components_total": {
                                        "rest_penalty": 0,
                                        "preferred_days_penalty": 30,
                                        "totals_penalty": 40,
                                        "fairness_penalty": 10,
                                        "weekday_patterns_penalty": 0,
                                        "weekday_patterns_bonus": 0,
                                        "friday_free_weekend_penalty": 0,
                                        "preferred_partners_bonus": 0.0,
                                    },
                                    "working_lock_version": 7,
                                },
                            },
                        },
                    }
                }
            },
        },
        404: {
            "description": "Not found (no working row or pointer/version missing).",
            "content": {"application/json": {"example": _err_example("not_found")}},
        },
        409: {
            "description": "Snapshot is required (NO FALLBACKS policy).",
            "content": {
                "application/json": {
                    "examples": {
                        "working_requires_snapshot": {
                            "summary": "Working diagnostics blocked: missing inputs_snapshot",
                            "value": _err_example(
                                "working_requires_snapshot",
                                detail="Cannot save or analyze this draft. Regenerate the schedule.",
                                context={"year": 2026, "month": 2, "operation": "get_diagnostics_working"},
                            ),
                        },
                        "diagnostics_requires_snapshot": {
                            "summary": "Version diagnostics blocked: missing inputs_snapshot",
                            "value": _err_example(
                                "diagnostics_requires_snapshot",
                                detail="Cannot compute diagnostics. Regenerate the schedule.",
                                context={"year": 2026, "month": 2, "version_id": 123},
                            ),
                        },
                    }
                }
            },
        },
        500: {
            "description": "Database error.",
            "content": {
                "application/json": {"example": _err_example("db_error", detail="Server error. Try again.", context={})}
            },
        },
    },
)
def schedules_diagnostics(
    user: UserCtx = Depends(require_admin),
    year: int = Path(..., ge=1900, le=2100, description="Calendar year"),
    month: int = Path(..., ge=1, le=12, description="Month 1..12"),
    target: Literal["working", "draft", "published"] = Query(
        ...,
        description=(
            "Which schedule source to analyze: "
            "'working' = live autosave buffer, "
            "'draft' = current draft pointer, "
            "'published' = current published pointer."
        ),
    ),
) -> DiagnosticsRead:
    try:
        return svc.get_diagnostics(year=year, month=month, target=target)
    except ValueError as e:
        _raise(e)
        assert False


# --------------------------- ADMIN: period view --------------------------


@router.get(
    "/{year}/{month}",
    response_model=SchedulesPeriodViewRead,
    tags=["schedules:admin"],
    summary="Period view (working + pointers + diagnostics) — service-built",
    description=(
        "Unified view for a period (working + current draft/published pointers).\n\n"
        "Note:\n"
        "- draft.payload / published.payload is null ONLY when the pointer does not exist.\n"
        "  If pointer exists, payload is always a full SchedulePayload (validated by the service)."
        "\n\n"
        "Diagnostics DTO notes (stable contract):\n"
        "- diagnostics.details.rankings uses keys: happy and unhappy (full lists).\n"
        "- DoctorRankingItemRead.score is the UI stars (1..5).\n"
        "- diagnostics.details.per_doctor items include categories and solver_components_by_doc.\n"
    ),
    responses={
        200: {
            "description": "Unified view for a period (includes empty skeleton when nothing exists).",
            "content": {
                "application/json": {
                    "examples": {
                        "empty_skeleton": {
                            "summary": "No data for the period yet",
                            "value": {
                                "year": 2026,
                                "month": 2,
                                "org_timezone": "Europe/Warsaw",
                                "period_status": "current",
                                "view": {"default_mode": "draft", "toggle_available": False},
                                "working": {
                                    "year": 2026,
                                    "month": 2,
                                    "exists": False,
                                    "participant_doctor_ids": [],
                                    "assignments": [],
                                    "meta": {"labels": []},
                                    "updated_at": None,
                                    "lock_version": None,
                                    "inputs_snapshot": None,
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
                                    "audit": None,
                                    "payload": None,
                                },
                                "diagnostics": None,
                            },
                        },
                        "with_draft": {
                            "summary": "Working exists and a draft pointer exists",
                            "value": {
                                "year": 2026,
                                "month": 2,
                                "org_timezone": "Europe/Warsaw",
                                "period_status": "current",
                                "view": {"default_mode": "draft", "toggle_available": False},
                                "working": {
                                    "year": 2026,
                                    "month": 2,
                                    "exists": True,
                                    "participant_doctor_ids": [101, 102, 103],
                                    "assignments": [{"day": 1, "shift_type": "onsite", "doctor_id": 101}],
                                    "meta": {"labels": []},
                                    "updated_at": "2026-01-28T09:30:00Z",
                                    "lock_version": 8,
                                    "inputs_snapshot": {
                                        "doctors": {
                                            "101": {
                                                "role": "specialist",
                                                "is_head": True,
                                                "display_name": "Jan Kowalski",
                                                "is_active_at_snapshot": True,
                                            }
                                        },
                                        "preference_version_id_by_doctor": {"101": 55},
                                    },
                                },
                                "draft": {
                                    "version_id": 124,
                                    "checkpoints_count": 2,
                                    "can_undo": True,
                                    "can_redo": False,
                                    "payload": {
                                        "participant_doctor_ids": [101, 102, 103],
                                        "assignments": [{"day": 1, "shift_type": "onsite", "doctor_id": 101}],
                                        "inputs_snapshot": {
                                            "doctors": {
                                                "101": {
                                                    "role": "specialist",
                                                    "is_head": True,
                                                    "display_name": "Jan Kowalski",
                                                    "is_active_at_snapshot": True,
                                                }
                                            },
                                            "preference_version_id_by_doctor": {"101": 55},
                                        },
                                        "meta": {"labels": []},
                                    },
                                },
                                "published": {
                                    "version_id": None,
                                    "publications_count": 0,
                                    "can_undo": False,
                                    "can_redo": False,
                                    "audit": None,
                                    "payload": None,
                                },
                                "diagnostics": {
                                    "version_id": 124,
                                    "computed_at": "2026-01-28T09:40:00Z",
                                    "summary": {
                                        "coverage_missing_required_slots": 0,
                                        "hard_issues_count": 0,
                                        "rest_violations": 0,
                                        "fairness_index": 1.0,
                                        "preference_fulfillment_pct": 100.0,
                                    },
                                    "details": {
                                        "findings": [
                                            {
                                                "code": _issue_code(issues.COVERAGE_MISSING_REQUIRED_SLOT),
                                                "severity": "critical",
                                                "context": {"day": 2, "shift_type": "onsite", "was_ignored": True},
                                            }
                                        ],
                                        "per_doctor": [
                                            {
                                                "doctor_id": 101,
                                                "display_name": "Doctor 101",
                                                "assigned_onsite_total": 5,
                                                "assigned_oncall_total": 3,
                                                "rest_violations": 0,
                                                "preferred_days_requested": 2,
                                                "preferred_days_missed": 1,
                                                "preference_fulfillment_pct": 78.0,
                                                "ui_stars": 3,
                                                "ui_reasons_codes": [
                                                    "preferred_days_missed",
                                                    "preferences_not_fully_met",
                                                ],
                                                "categories": _example_categories(),
                                                "solver_components_by_doc": _example_solver_components_by_doc(),
                                            }
                                        ],
                                        "rankings": {
                                            "unhappy": [
                                                {
                                                    "doctor_id": 101,
                                                    "score": 3,
                                                    "reasons_codes": ["preferred_days_missed"],
                                                }
                                            ],
                                            "happy": [],
                                        },
                                        "audit": [
                                            {
                                                "kind": "generation_ignore",
                                                "code": _issue_code(issues.COVERAGE_IGNORED_SLOT),
                                                "day": 2,
                                                "shift_type": "onsite",
                                                "justification": "Holiday staffing shortage "
                                                "— generating draft with gaps.",
                                                "accepted_by_user_id": 1,
                                                "accepted_at": "2026-01-28T09:10:00Z",
                                            }
                                        ],
                                        "solver_components_total": {
                                            "rest_penalty": 0,
                                            "preferred_days_penalty": 30,
                                            "totals_penalty": 40,
                                            "fairness_penalty": 10,
                                            "weekday_patterns_penalty": 0,
                                            "weekday_patterns_bonus": 0,
                                            "friday_free_weekend_penalty": 0,
                                            "preferred_partners_bonus": 0.0,
                                        },
                                        "working_lock_version": 7,
                                    },
                                },
                            },
                        },
                        "with_draft_and_published": {
                            "summary": "Both pointers exist (toggle is available)",
                            "value": {
                                "year": 2026,
                                "month": 2,
                                "org_timezone": "Europe/Warsaw",
                                "period_status": "current",
                                "view": {"default_mode": "draft", "toggle_available": True},
                                "working": {
                                    "year": 2026,
                                    "month": 2,
                                    "exists": True,
                                    "participant_doctor_ids": [101, 102, 103],
                                    "assignments": [
                                        {"day": 1, "shift_type": "onsite", "doctor_id": 101},
                                        {"day": 1, "shift_type": "oncall", "doctor_id": 102},
                                    ],
                                    "meta": {"labels": ["edited_by_admin"]},
                                    "updated_at": "2026-01-28T09:30:00Z",
                                    "lock_version": 8,
                                    "inputs_snapshot": {
                                        "doctors": {
                                            "101": {
                                                "role": "specialist",
                                                "is_head": True,
                                                "display_name": "Jan Kowalski",
                                                "is_active_at_snapshot": True,
                                            },
                                            "102": {
                                                "role": "resident",
                                                "is_head": False,
                                                "display_name": "Doctor 102",
                                                "is_active_at_snapshot": True,
                                            },
                                        },
                                        "preference_version_id_by_doctor": {"101": 55, "102": 56},
                                    },
                                },
                                "draft": {
                                    "version_id": 124,
                                    "checkpoints_count": 2,
                                    "can_undo": True,
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
                                                },
                                                "102": {
                                                    "role": "resident",
                                                    "is_head": False,
                                                    "display_name": "Doctor 102",
                                                    "is_active_at_snapshot": True,
                                                },
                                            },
                                            "preference_version_id_by_doctor": {"101": 55, "102": 56},
                                        },
                                        "meta": {"labels": ["as_generated"]},
                                    },
                                },
                                "published": {
                                    "version_id": 200,
                                    "publications_count": 1,
                                    "can_undo": False,
                                    "can_redo": False,
                                    "audit": {"published_at": "2026-01-28T10:00:00Z"},
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
                                                },
                                                "102": {
                                                    "role": "resident",
                                                    "is_head": False,
                                                    "display_name": "Doctor 102",
                                                    "is_active_at_snapshot": True,
                                                },
                                            },
                                            "preference_version_id_by_doctor": {"101": 55, "102": 56},
                                        },
                                        "meta": {"labels": ["as_generated"], "note": "Finalize"},
                                    },
                                },
                                "diagnostics": {
                                    "version_id": 124,
                                    "computed_at": "2026-01-28T09:40:00Z",
                                    "summary": {
                                        "coverage_missing_required_slots": 0,
                                        "hard_issues_count": 0,
                                        "rest_violations": 0,
                                        "fairness_index": 1.0,
                                        "preference_fulfillment_pct": 100.0,
                                    },
                                    "details": {
                                        "findings": [
                                            {
                                                "code": _issue_code(issues.COVERAGE_MISSING_REQUIRED_SLOT),
                                                "severity": "critical",
                                                "context": {"day": 2, "shift_type": "onsite", "was_ignored": True},
                                            }
                                        ],
                                        "per_doctor": [
                                            {
                                                "doctor_id": 101,
                                                "display_name": "Doctor 101",
                                                "assigned_onsite_total": 5,
                                                "assigned_oncall_total": 3,
                                                "rest_violations": 0,
                                                "preferred_days_requested": 2,
                                                "preferred_days_missed": 1,
                                                "preference_fulfillment_pct": 78.0,
                                                "ui_stars": 3,
                                                "ui_reasons_codes": [
                                                    "preferred_days_missed",
                                                    "preferences_not_fully_met",
                                                ],
                                                "categories": _example_categories(),
                                                "solver_components_by_doc": _example_solver_components_by_doc(),
                                            }
                                        ],
                                        "rankings": {
                                            "unhappy": [
                                                {
                                                    "doctor_id": 101,
                                                    "score": 3,
                                                    "reasons_codes": ["preferred_days_missed"],
                                                }
                                            ],
                                            "happy": [],
                                        },
                                        "audit": [
                                            {
                                                "kind": "generation_ignore",
                                                "code": _issue_code(issues.COVERAGE_IGNORED_SLOT),
                                                "day": 2,
                                                "shift_type": "onsite",
                                                "justification": "Holiday staffing shortage "
                                                "— generating draft with gaps.",
                                                "accepted_by_user_id": 1,
                                                "accepted_at": "2026-01-28T09:10:00Z",
                                            }
                                        ],
                                        "solver_components_total": {
                                            "rest_penalty": 0,
                                            "preferred_days_penalty": 30,
                                            "totals_penalty": 40,
                                            "fairness_penalty": 10,
                                            "weekday_patterns_penalty": 0,
                                            "weekday_patterns_bonus": 0,
                                            "friday_free_weekend_penalty": 0,
                                            "preferred_partners_bonus": 0.0,
                                        },
                                        "working_lock_version": 7,
                                    },
                                },
                            },
                        },
                    }
                }
            },
        },
        404: {
            "description": "Not found (pointer exists but version row missing, etc.).",
            "content": {"application/json": {"example": _err_example("not_found")}},
        },
        409: {
            "description": "Snapshot required to compute diagnostics for the current draft pointer (NO FALLBACKS).",
            "content": {
                "application/json": {
                    "example": _err_example(
                        "diagnostics_requires_snapshot",
                        detail="Cannot compute diagnostics. Regenerate the schedule.",
                        context={"year": 2026, "month": 2, "version_id": 124},
                    )
                }
            },
        },
        500: {
            "description": "Database error.",
            "content": {
                "application/json": {"example": _err_example("db_error", detail="Database error.", context={})}
            },
        },
    },
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
    description=(
        "Return the current *working buffer* (admin draft) for the selected month.\n\n"
        "If no working row exists yet, returns a *skeleton* with `exists=false` and empty arrays.\n\n"
        "Important fields:\n"
        "- `exists`: tells FE whether a persisted working row exists.\n"
        "- `lock_version`: optimistic concurrency token (echo in PUT as `if_match_lock_version`).\n"
        "- `inputs_snapshot`: frozen inputs used to generate the schedule; required for manual edits.\n"
    ),
    responses={
        200: {
            "description": "Working buffer (or skeleton with exists=false).",
            "content": {
                "application/json": {
                    "examples": {
                        "exists_true": {
                            "summary": "Working exists",
                            "value": {
                                "year": 2026,
                                "month": 2,
                                "exists": True,
                                "participant_doctor_ids": [1, 2, 3],
                                "assignments": [
                                    {"day": 1, "shift_type": "onsite", "doctor_id": 2},
                                    {"day": 1, "shift_type": "oncall", "doctor_id": 1},
                                ],
                                "meta": {"labels": ["edited_by_admin"], "exceptions": []},
                                "updated_at": "2026-02-02T10:15:30Z",
                                "lock_version": 7,
                                "inputs_snapshot": None,
                            },
                        },
                        "exists_false": {
                            "summary": "Skeleton (no working row yet)",
                            "value": {
                                "year": 2026,
                                "month": 2,
                                "exists": False,
                                "participant_doctor_ids": [],
                                "assignments": [],
                                "meta": {"labels": []},
                                "updated_at": None,
                                "lock_version": None,
                                "inputs_snapshot": None,
                            },
                        },
                    }
                }
            },
        },
        403: {
            "description": "Period is closed.",
            "content": {"application/json": {"example": _err_example("period_closed")}},
        },
        404: {"description": "Not found.", "content": {"application/json": {"example": _err_example("not_found")}}},
        500: {"description": "DB error.", "content": {"application/json": {"example": _err_example("db_error")}}},
    },
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
    description=(
        "Autosave the *working buffer* (admin draft). This overwrites the working payload only "
        "(no checkpoint/draft version is created).\n\n"
        "Concurrency (OCC):\n"
        "- If `if_match_lock_version` is provided and mismatches the current `lock_version`, "
        "the server returns `409 edit_conflict`.\n\n"
        "Snapshot requirement (NO FALLBACKS policy):\n"
        "- Manual edits are allowed only when the working payload already contains `inputs_snapshot`.\n"
        "  If missing, server returns `409 working_requires_snapshot`.\n\n"
        "Meta rules enforced by server:\n"
        "- Always remove label `as_generated`.\n"
        "- Always add label `edited_by_admin`.\n"
        "- Preserve/merge `meta.exceptions` (existing exceptions are never dropped).\n\n"
        "Returns a lean ACK with `updated_at` and the new `lock_version`.\n"
    ),
    responses={
        200: {
            "description": "Autosave accepted (lean ACK).",
            "content": {
                "application/json": {
                    "example": {
                        "year": 2026,
                        "month": 2,
                        "updated_at": "2026-02-02T10:16:10Z",
                        "lock_version": 8,
                    }
                }
            },
        },
        409: {
            "description": "Conflict (OCC mismatch or missing snapshot).",
            "content": {
                "application/json": {
                    "examples": {
                        "edit_conflict": {
                            "summary": "OCC mismatch",
                            "value": _err_example("edit_conflict"),
                        },
                        "working_requires_snapshot": {
                            "summary": "Working has no inputs_snapshot (manual edits blocked)",
                            "value": _err_example(
                                "working_requires_snapshot",
                                context={"year": 2026, "month": 2, "operation": "save_working"},
                            ),
                        },
                    }
                }
            },
        },
        400: {
            "description": "Bad request (invalid payload).",
            "content": {"application/json": {"example": _err_example("invalid_accepted_exception")}},
        },
        403: {
            "description": "Period is closed.",
            "content": {"application/json": {"example": _err_example("period_closed")}},
        },
        500: {"description": "DB error.", "content": {"application/json": {"example": _err_example("db_error")}}},
    },
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
    description=(
        "Create a new immutable DRAFT checkpoint from the current WORKING schedule.\n\n"
        "FE behavior:\n"
        "- Call this on explicit user action (e.g. Save button).\n"
        "- After 201, refresh UI state using the returned draft + diagnostics.\n"
        "- If blocked by 409 diagnostics_requires_snapshot, the schedule must be regenerated (NO FALLBACKS).\n"
    ),
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": _OPENAPI_EXAMPLES_CHECKPOINT_REQUEST,
                }
            }
        }
    },
    responses={
        201: {
            "description": "Draft checkpoint created from working; diagnostics computed.",
            "content": {
                "application/json": {
                    "example": {
                        "year": 2026,
                        "month": 2,
                        "draft": {
                            "version_id": 124,
                            "checkpoints_count": 2,
                            "can_undo": True,
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
                                    "preference_version_id_by_doctor": {"101": 55},
                                },
                                "meta": {"labels": []},
                            },
                        },
                        "diagnostics": {
                            "version_id": 124,
                            "computed_at": "2026-01-28T09:40:00Z",
                            "summary": {
                                "coverage_missing_required_slots": 0,
                                "hard_issues_count": 0,
                                "rest_violations": 0,
                                "fairness_index": 1.0,
                                "preference_fulfillment_pct": 100.0,
                            },
                            "details": {
                                "findings": [
                                    {
                                        "code": _issue_code(issues.COVERAGE_MISSING_REQUIRED_SLOT),
                                        "severity": "critical",
                                        "context": {"day": 2, "shift_type": "onsite", "was_ignored": True},
                                    }
                                ],
                                "per_doctor": [
                                    {
                                        "doctor_id": 101,
                                        "display_name": "Doctor 101",
                                        "assigned_onsite_total": 5,
                                        "assigned_oncall_total": 3,
                                        "rest_violations": 0,
                                        "preferred_days_requested": 2,
                                        "preferred_days_missed": 1,
                                        "preference_fulfillment_pct": 78.0,
                                        "ui_stars": 3,
                                        "ui_reasons_codes": ["preferred_days_missed", "preferences_not_fully_met"],
                                        "categories": _example_categories(),
                                        "solver_components_by_doc": _example_solver_components_by_doc(),
                                    }
                                ],
                                "rankings": {
                                    "unhappy": [
                                        {"doctor_id": 101, "score": 3, "reasons_codes": ["preferred_days_missed"]}
                                    ],
                                    "happy": [],
                                },
                                "audit": [
                                    {
                                        "kind": "generation_ignore",
                                        "code": _issue_code(issues.COVERAGE_IGNORED_SLOT),
                                        "day": 2,
                                        "shift_type": "onsite",
                                        "justification": "Holiday staffing shortage — generating draft with gaps.",
                                        "accepted_by_user_id": 1,
                                        "accepted_at": "2026-01-28T09:10:00Z",
                                    }
                                ],
                                "solver_components_total": {
                                    "rest_penalty": 0,
                                    "preferred_days_penalty": 30,
                                    "totals_penalty": 40,
                                    "fairness_penalty": 10,
                                    "weekday_patterns_penalty": 0,
                                    "weekday_patterns_bonus": 0,
                                    "friday_free_weekend_penalty": 0,
                                    "preferred_partners_bonus": 0.0,
                                },
                                "working_lock_version": 7,
                            },
                        },
                    }
                }
            },
        },
        404: {
            "description": "Not found (e.g., working missing).",
            "content": {"application/json": {"example": _err_example("not_found")}},
        },
        409: {
            "description": "Snapshot is required to compute diagnostics for the checkpoint.",
            "content": {
                "application/json": {
                    "example": _err_example(
                        "diagnostics_requires_snapshot",
                        detail="Cannot compute diagnostics. Regenerate the schedule.",
                        context={"year": 2026, "month": 2, "version_id": 124},
                    )
                }
            },
        },
        500: {
            "description": "Database error.",
            "content": {
                "application/json": {"example": _err_example("db_error", detail="Database error.", context={})}
            },
        },
    },
)
def schedules_checkpoint(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    body: ScheduleCheckpointRequest | None = Body(None),
    user: UserCtx = Depends(require_admin),
) -> ScheduleCheckpointCreated:
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
    description=(
        "Move the DRAFT pointer to the previous checkpoint (UNDO) and overwrite WORKING with that snapshot.\n\n"
        "FE behavior:\n"
        "- After 200, re-render the grid from working.assignments.\n"
        "- Update undo/redo buttons from draft.can_undo / draft.can_redo.\n"
        "- Update diagnostics panel from the returned diagnostics.\n"
    ),
    responses={
        200: {
            "description": "Draft pointer moved to previous checkpoint; working overwritten; diagnostics returned.",
            "content": {
                "application/json": {
                    "example": {
                        "year": 2026,
                        "month": 2,
                        "draft": {
                            "version_id": 120,
                            "checkpoints_count": 5,
                            "can_undo": True,
                            "can_redo": True,
                            "payload": {
                                "participant_doctor_ids": [101, 102, 103],
                                "assignments": [{"day": 1, "shift_type": "onsite", "doctor_id": 101}],
                                "inputs_snapshot": {
                                    "doctors": {
                                        "101": {
                                            "role": "specialist",
                                            "is_head": True,
                                            "display_name": "Jan Kowalski",
                                            "is_active_at_snapshot": True,
                                        }
                                    },
                                    "preference_version_id_by_doctor": {"101": 55},
                                },
                                "meta": {"labels": ["as_generated"]},
                            },
                        },
                        "working": {
                            "year": 2026,
                            "month": 2,
                            "exists": True,
                            "participant_doctor_ids": [101, 102, 103],
                            "assignments": [{"day": 1, "shift_type": "onsite", "doctor_id": 101}],
                            "meta": {"labels": []},
                            "updated_at": "2026-01-28T09:45:00Z",
                            "lock_version": 9,
                            "inputs_snapshot": {
                                "doctors": {
                                    "101": {
                                        "role": "specialist",
                                        "is_head": True,
                                        "display_name": "Jan Kowalski",
                                        "is_active_at_snapshot": True,
                                    }
                                },
                                "preference_version_id_by_doctor": {"101": 55},
                            },
                        },
                        "diagnostics": {
                            "version_id": 120,
                            "computed_at": "2026-01-28T09:45:01Z",
                            "summary": {
                                "coverage_missing_required_slots": 0,
                                "hard_issues_count": 0,
                                "rest_violations": 0,
                                "fairness_index": 1.0,
                                "preference_fulfillment_pct": 100.0,
                            },
                            "details": {
                                "findings": [
                                    {
                                        "code": _issue_code(issues.COVERAGE_MISSING_REQUIRED_SLOT),
                                        "severity": "critical",
                                        "context": {"day": 2, "shift_type": "onsite", "was_ignored": True},
                                    }
                                ],
                                "per_doctor": [
                                    {
                                        "doctor_id": 101,
                                        "display_name": "Doctor 101",
                                        "assigned_onsite_total": 5,
                                        "assigned_oncall_total": 3,
                                        "rest_violations": 0,
                                        "preferred_days_requested": 2,
                                        "preferred_days_missed": 1,
                                        "preference_fulfillment_pct": 78.0,
                                        "ui_stars": 3,
                                        "ui_reasons_codes": ["preferred_days_missed", "preferences_not_fully_met"],
                                        "categories": _example_categories(),
                                        "solver_components_by_doc": _example_solver_components_by_doc(),
                                    }
                                ],
                                "rankings": {
                                    "unhappy": [
                                        {"doctor_id": 101, "score": 3, "reasons_codes": ["preferred_days_missed"]}
                                    ],
                                    "happy": [],
                                },
                                "audit": [
                                    {
                                        "kind": "generation_ignore",
                                        "code": _issue_code(issues.COVERAGE_IGNORED_SLOT),
                                        "day": 2,
                                        "shift_type": "onsite",
                                        "justification": "Holiday staffing shortage — generating draft with gaps.",
                                        "accepted_by_user_id": 1,
                                        "accepted_at": "2026-01-28T09:10:00Z",
                                    }
                                ],
                                "solver_components_total": {
                                    "rest_penalty": 0,
                                    "preferred_days_penalty": 30,
                                    "totals_penalty": 40,
                                    "fairness_penalty": 10,
                                    "weekday_patterns_penalty": 0,
                                    "weekday_patterns_bonus": 0,
                                    "friday_free_weekend_penalty": 0,
                                    "preferred_partners_bonus": 0.0,
                                },
                                "working_lock_version": 7,
                            },
                        },
                    }
                }
            },
        },
        409: {
            "description": "No earlier version available.",
            "content": {
                "application/json": {
                    "examples": {
                        "cannot_undo": {
                            "summary": "No earlier draft checkpoint available.",
                            "value": _err_example("cannot_undo"),
                        },
                        "diagnostics_requires_snapshot": {
                            "summary": "Revert blocked: version payload has no inputs_snapshot (NO FALLBACKS).",
                            "value": _err_example(
                                "diagnostics_requires_snapshot",
                                detail="Cannot compute diagnostics. Regenerate the schedule.",
                                context={"year": 2026, "month": 2, "version_id": 120},
                            ),
                        },
                    }
                }
            },
        },
        404: {"description": "Not found.", "content": {"application/json": {"example": _err_example("not_found")}}},
        500: {
            "description": "Database error.",
            "content": {
                "application/json": {"example": _err_example("db_error", detail="Database error.", context={})}
            },
        },
    },
)
def schedules_draft_undo(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    user: UserCtx = Depends(require_admin),
) -> ScheduleRevertRead:
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
    description=(
        "Move the DRAFT pointer to the next checkpoint (REDO) and overwrite WORKING with that snapshot.\n\n"
        "FE behavior:\n"
        "- After 200, re-render the grid from working.assignments.\n"
        "- Update undo/redo buttons from draft.can_undo / draft.can_redo.\n"
        "- Update diagnostics panel from the returned diagnostics.\n"
    ),
    responses={
        200: {
            "description": "Draft pointer moved to next checkpoint; working overwritten; diagnostics returned.",
            "content": {
                "application/json": {
                    "example": {
                        "year": 2026,
                        "month": 2,
                        "draft": {
                            "version_id": 121,
                            "checkpoints_count": 5,
                            "can_undo": True,
                            "can_redo": True,
                            "payload": {
                                "participant_doctor_ids": [101, 102, 103],
                                "assignments": [{"day": 1, "shift_type": "oncall", "doctor_id": 102}],
                                "inputs_snapshot": {
                                    "doctors": {
                                        "101": {
                                            "role": "specialist",
                                            "is_head": True,
                                            "display_name": "Jan Kowalski",
                                            "is_active_at_snapshot": True,
                                        }
                                    },
                                    "preference_version_id_by_doctor": {"101": 55},
                                },
                                "meta": {"labels": ["as_generated"]},
                            },
                        },
                        "working": {
                            "year": 2026,
                            "month": 2,
                            "exists": True,
                            "participant_doctor_ids": [101, 102, 103],
                            "assignments": [{"day": 1, "shift_type": "oncall", "doctor_id": 102}],
                            "meta": {"labels": []},
                            "updated_at": "2026-01-28T09:50:00Z",
                            "lock_version": 10,
                            "inputs_snapshot": {
                                "doctors": {
                                    "101": {
                                        "role": "specialist",
                                        "is_head": True,
                                        "display_name": "Jan Kowalski",
                                        "is_active_at_snapshot": True,
                                    }
                                },
                                "preference_version_id_by_doctor": {"101": 55},
                            },
                        },
                        "diagnostics": {
                            "version_id": 121,
                            "computed_at": "2026-01-28T09:50:01Z",
                            "summary": {
                                "coverage_missing_required_slots": 0,
                                "hard_issues_count": 0,
                                "rest_violations": 0,
                                "fairness_index": 1.0,
                                "preference_fulfillment_pct": 100.0,
                            },
                            "details": {
                                "findings": [
                                    {
                                        "code": _issue_code(issues.COVERAGE_MISSING_REQUIRED_SLOT),
                                        "severity": "critical",
                                        "context": {"day": 2, "shift_type": "onsite", "was_ignored": True},
                                    }
                                ],
                                "per_doctor": [
                                    {
                                        "doctor_id": 101,
                                        "display_name": "Doctor 101",
                                        "assigned_onsite_total": 5,
                                        "assigned_oncall_total": 3,
                                        "rest_violations": 0,
                                        "preferred_days_requested": 2,
                                        "preferred_days_missed": 1,
                                        "preference_fulfillment_pct": 78.0,
                                        "ui_stars": 3,
                                        "ui_reasons_codes": ["preferred_days_missed", "preferences_not_fully_met"],
                                        "categories": _example_categories(),
                                        "solver_components_by_doc": _example_solver_components_by_doc(),
                                    }
                                ],
                                "rankings": {
                                    "unhappy": [
                                        {"doctor_id": 101, "score": 3, "reasons_codes": ["preferred_days_missed"]}
                                    ],
                                    "happy": [],
                                },
                                "audit": [
                                    {
                                        "kind": "generation_ignore",
                                        "code": _issue_code(issues.COVERAGE_IGNORED_SLOT),
                                        "day": 2,
                                        "shift_type": "onsite",
                                        "justification": "Holiday staffing shortage — generating draft with gaps.",
                                        "accepted_by_user_id": 1,
                                        "accepted_at": "2026-01-28T09:10:00Z",
                                    }
                                ],
                                "solver_components_total": {
                                    "rest_penalty": 0,
                                    "preferred_days_penalty": 30,
                                    "totals_penalty": 40,
                                    "fairness_penalty": 10,
                                    "weekday_patterns_penalty": 0,
                                    "weekday_patterns_bonus": 0,
                                    "friday_free_weekend_penalty": 0,
                                    "preferred_partners_bonus": 0.0,
                                },
                                "working_lock_version": 7,
                            },
                        },
                    }
                }
            },
        },
        409: {
            "description": "No later version available.",
            "content": {
                "application/json": {
                    "examples": {
                        "cannot_redo": {
                            "summary": "No later draft checkpoint available.",
                            "value": _err_example("cannot_redo"),
                        },
                        "diagnostics_requires_snapshot": {
                            "summary": "Revert blocked: version payload has no inputs_snapshot (NO FALLBACKS).",
                            "value": _err_example(
                                "diagnostics_requires_snapshot",
                                detail="Cannot compute diagnostics. Regenerate the schedule.",
                                context={"year": 2026, "month": 2, "version_id": 121},
                            ),
                        },
                    }
                }
            },
        },
        404: {"description": "Not found.", "content": {"application/json": {"example": _err_example("not_found")}}},
        500: {
            "description": "Database error.",
            "content": {
                "application/json": {"example": _err_example("db_error", detail="Database error.", context={})}
            },
        },
    },
)
def schedules_draft_redo(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    user: UserCtx = Depends(require_admin),
) -> ScheduleRevertRead:
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
    summary="Publish from working (blocked by critical diagnostics; force supported)",
    description=(
        "Create a new PUBLISHED snapshot for {year, month} from the current WORKING schedule.\n\n"
        "Publishing is protected by critical blockers (hard-rule violations):\n"
        "- If force=false and diagnostics contain ANY severity='critical' finding -> blocked with 409.\n"
        "- If force=true -> publish proceeds, and FE should send accepted_exceptions built from ALL blocker codes\n"
        "  returned by the 409 response (bulk accept).\n\n"
        "Notes:\n"
        "- 'note' is an admin announcement stored into the published payload (payload.meta.note) so doctors can\n"
        "  read it later via GET /{year}/{month}/published.\n"
        "- accepted_exceptions[].justification is audit-only history for force publish (NOT shown to doctors).\n"
        "- Rest findings do NOT block publish (rest is not a hard rule).\n"
    ),
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": _OPENAPI_EXAMPLES_PUBLISH_REQUEST,
                }
            }
        }
    },
    responses={
        201: {
            "description": "Published version created from working.",
            "content": {
                "application/json": {
                    "example": {
                        "year": 2026,
                        "month": 2,
                        "published": {
                            "version_id": 200,
                            "publications_count": 1,
                            "can_undo": False,
                            "can_redo": False,
                            "audit": {
                                "published_at": "2026-01-28T10:00:00Z",
                                "published_by_user_id": 1,
                                "note": "Finalize",
                            },
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
                                        },
                                        "102": {
                                            "role": "resident",
                                            "is_head": False,
                                            "display_name": "Doctor 102",
                                            "is_active_at_snapshot": True,
                                        },
                                    },
                                    "preference_version_id_by_doctor": {"101": 55, "102": 56},
                                },
                                "meta": {"labels": ["as_generated"], "note": "Finalize"},
                            },
                        },
                    }
                }
            },
        },
        409: {
            "description": "Publishing blocked by critical diagnostics findings (unless force=True).",
            "content": {
                "application/json": {
                    "examples": {
                        "publish_requires_snapshot": {
                            "summary": "Publish blocked: missing inputs_snapshot",
                            "value": _err_example(
                                "publish_requires_snapshot",
                                detail="Cannot publish. Regenerate the schedule first.",
                                context={"year": 2026, "month": 2},
                            ),
                        },
                        "publish_blocked_by_hard_rules": {
                            "summary": "Publish blocked (force=False). "
                            "FE may retry with force=True (accept ALL blockers).",
                            "value": _err_example(
                                "publish_blocked_by_hard_rules",
                                detail="Publishing blocked: hard rule violations detected. "
                                "Fix them or use Force Publish.",
                                context={
                                    "year": 2026,
                                    "month": 2,
                                    "hard_violations": [
                                        {
                                            "code": _issue_code(issues.COVERAGE_MISSING_REQUIRED_SLOT),
                                            "message": "",
                                            "context": {"day": 10, "shift_type": "oncall", "was_ignored": False},
                                        },
                                        {
                                            "code": _issue_code(issues.COVERAGE_NO_SPECIALIST_DAY),
                                            "message": "",
                                            "context": {
                                                "day": 12,
                                                "day_empty": True,
                                                "assigned_doctor_ids": [],
                                                "was_ignored_day": False,
                                                "was_ignored_onsite": False,
                                                "was_ignored_oncall": False,
                                            },
                                        },
                                        {
                                            "code": _issue_code(issues.HARD_DOUBLE_SHIFT_SAME_DAY),
                                            "message": "",
                                            "context": {"doctor_id": 101, "day": 15},
                                        },
                                    ],
                                    "diagnostics_summary": {
                                        "coverage_missing_required_slots": 1,
                                        "hard_issues_count": 1,
                                        "rest_violations": 0,
                                        "fairness_index": 0.95,
                                        "preference_fulfillment_pct": 82.0,
                                    },
                                    # NOTE:
                                    # - generation_exceptions are run/audit metadata (not diagnostics findings).
                                    # - slot markers use coverage_ignored_slot and include day+shift_type
                                    # - action rows use "generation_ignore" and may omit day/shift_type
                                    "generation_exceptions": [
                                        {
                                            "kind": "generation_ignore",
                                            "code": _issue_code(issues.COVERAGE_IGNORED_SLOT),
                                            "day": 2,
                                            "shift_type": "onsite",
                                        },
                                        {
                                            "kind": "generation_ignore",
                                            "code": "generation_ignore",
                                            "justification": "Ignored some slots to allow generation; "
                                            "duty shortage documented.",
                                        },
                                    ],
                                },
                            ),
                        },
                    }
                }
            },
        },
        400: {
            "description": "Invalid accepted exception payload.",
            "content": {"application/json": {"example": _err_example("invalid_accepted_exception")}},
        },
        404: {"description": "Not found.", "content": {"application/json": {"example": _err_example("not_found")}}},
        500: {
            "description": "Database error.",
            "content": {
                "application/json": {"example": _err_example("db_error", detail="Database error.", context={})}
            },
        },
    },
)
def schedules_publish(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    body: SchedulePublishRequest = Body(...),
    user: UserCtx = Depends(require_admin),
) -> SchedulePublishCreated:
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


# ----------------------- ADMIN: published undo/redo ---------------------


@router.post(
    "/{year}/{month}/revert-last-published",
    response_model=SchedulePublishedRevertRead,
    tags=["schedules:admin"],
    summary="Published rollback (pointer → previous published)",
    description=(
        "Move the PUBLISHED pointer to the previous published version.\n\n"
        "FE behavior:\n"
        "- After 200, refresh the published view (grid) from the returned published.payload.\n"
        "- Update buttons from published.can_undo / published.can_redo.\n"
    ),
    responses={
        200: {
            "description": "Published pointer moved to previous published version (does not touch working).",
            "content": {
                "application/json": {
                    "example": {
                        "year": 2026,
                        "month": 2,
                        "published": {
                            "version_id": 199,
                            "publications_count": 2,
                            "can_undo": False,
                            "can_redo": True,
                            "audit": {},
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
                                    "preference_version_id_by_doctor": {"101": 55},
                                },
                                "meta": {"labels": ["as_generated"], "note": "Finalize"},
                            },
                        },
                    }
                }
            },
        },
        409: {
            "description": "No earlier published version available.",
            "content": {"application/json": {"example": _err_example("cannot_undo")}},
        },
        404: {"description": "Not found.", "content": {"application/json": {"example": _err_example("not_found")}}},
        500: {
            "description": "Database error.",
            "content": {
                "application/json": {"example": _err_example("db_error", detail="Database error.", context={})}
            },
        },
    },
)
def schedules_published_undo(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    user: UserCtx = Depends(require_admin),
) -> SchedulePublishedRevertRead:
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
    description=(
        "Move the PUBLISHED pointer to the next published version.\n\n"
        "FE behavior:\n"
        "- After 200, refresh the published view from the returned published.payload.\n"
        "- Update buttons from published.can_undo / published.can_redo.\n"
    ),
    responses={
        200: {
            "description": "Published pointer moved to next published version (does not touch working).",
            "content": {
                "application/json": {
                    "example": {
                        "year": 2026,
                        "month": 2,
                        "published": {
                            "version_id": 200,
                            "publications_count": 2,
                            "can_undo": True,
                            "can_redo": False,
                            "audit": {},
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
                                    "preference_version_id_by_doctor": {"101": 55},
                                },
                                "meta": {"labels": ["as_generated"], "note": "Finalize"},
                            },
                        },
                    }
                }
            },
        },
        409: {
            "description": "No later published version available.",
            "content": {"application/json": {"example": _err_example("cannot_redo")}},
        },
        404: {"description": "Not found.", "content": {"application/json": {"example": _err_example("not_found")}}},
        500: {
            "description": "Database error.",
            "content": {
                "application/json": {"example": _err_example("db_error", detail="Database error.", context={})}
            },
        },
    },
)
def schedules_published_redo(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    user: UserCtx = Depends(require_admin),
) -> SchedulePublishedRevertRead:
    try:
        return cast(
            SchedulePublishedRevertRead,
            svc.revert(year, month, target="published", direction="next", user_id=user.user_id if user else None),
        )
    except ValueError as e:
        _raise(e)
        assert False


# --------------------------- EXPORT (placeholder) ----------------------------


@router.get(
    "/export",
    tags=["schedules:export"],
    summary="Unified export for admins & doctors (xlsx/pdf/ics)",
    operation_id="schedules_export_get",
    responses={
        501: {
            "description": "Not implemented.",
            "content": {"application/json": {"example": _err_example("not_implemented", context={})}},
        },
    },
)
def schedules_export(
    year: int = Query(..., ge=1900, le=2100),
    month: int = Query(..., ge=1, le=12),
    mode: Literal["draft", "published"] = Query(...),
    format: Literal["xlsx", "pdf", "ics"] = Query(...),
    doctor_id: Optional[int] = Query(None, ge=1),
    user: UserCtx = Depends(require_admin),
):
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=make_error("not_implemented", context={}),
    )


# --------------------------- DOCTOR: read published ----------------------------


@router.get(
    "/{year}/{month}/published",
    response_model=SchedulePublishedRead,
    tags=["schedules:doctor"],
    summary="Read current PUBLISHED schedule for the period (pointer-based)",
    description=(
        "Doctor read endpoint for the current published schedule.\n\n"
        "FE behavior:\n"
        "- Render the schedule grid from published.payload.assignments.\n"
        "- Show the admin announcement from published.payload.meta.note if present.\n"
        "- Use this endpoint as the canonical doctor-visible schedule source.\n"
    ),
    responses={
        200: {
            "description": "Current published schedule snapshot for the period.",
            "content": {
                "application/json": {
                    "example": {
                        "year": 2026,
                        "month": 2,
                        "org_timezone": "Europe/Warsaw",
                        "period_status": "current",
                        "published": {
                            "version_id": 200,
                            "publications_count": 1,
                            "can_undo": False,
                            "can_redo": False,
                            "audit": {"published_at": "2026-01-28T10:00:00Z"},
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
                                        },
                                        "102": {
                                            "role": "resident",
                                            "is_head": False,
                                            "display_name": "Doctor 102",
                                            "is_active_at_snapshot": True,
                                        },
                                    },
                                    "preference_version_id_by_doctor": {"101": 55, "102": 56},
                                },
                                "meta": {
                                    "labels": [],
                                    "note": "Happy holidays! "
                                    "Please double-check your shifts and contact admin if needed.",
                                },
                            },
                        },
                    }
                }
            },
        },
        404: {
            "description": "Not found (no published pointer/version for this period).",
            "content": {
                "application/json": {
                    "examples": {
                        "published_missing": {
                            "summary": "No published schedule for this period (pointer missing "
                            "or published pointer is empty)",
                            "value": _err_example(
                                "not_found",
                                detail="not_found",
                                context={
                                    "where": "get_published.pointer_or_published_missing",
                                    "year": 2026,
                                    "month": 2,
                                    "has_pointer": False,
                                    "published_version_id": None,
                                },
                            ),
                        },
                        "published_version_missing": {
                            "summary": "Published pointer exists, but the pointed version row is missing",
                            "value": _err_example(
                                "not_found",
                                detail="not_found",
                                context={
                                    "where": "get_published.published_version_missing",
                                    "year": 2026,
                                    "month": 2,
                                    "published_version_id": 200,
                                },
                            ),
                        },
                    }
                }
            },
        },
        500: {
            "description": "Database error.",
            "content": {
                "application/json": {"example": _err_example("db_error", detail="Database error.", context={})}
            },
        },
    },
)
def schedules_published_read(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    user: UserCtx = Depends(require_doctor),
) -> SchedulePublishedRead:
    try:
        return svc.get_published(year, month)
    except ValueError as e:
        _raise(e)
        assert False


# ---------------------- DOCTOR: my assignments -------------------


@router.get(
    "/{year}/{month}/my-assignments",
    response_model=MyAssignmentsRead,
    tags=["schedules:doctor"],
    summary="List my assignments from the current PUBLISHED schedule",
    responses={
        200: {
            "description": "My assignments extracted from current published schedule.",
            "content": {
                "application/json": {
                    "example": {
                        "doctor_id": 101,
                        "year": 2026,
                        "month": 2,
                        "assignments": [
                            {"day": 1, "shift_type": "onsite"},
                            {"day": 5, "shift_type": "oncall"},
                        ],
                    }
                }
            },
        },
        404: {
            "description": "Not found (no published pointer/version for this period).",
            "content": {
                "application/json": {
                    "examples": {
                        "published_missing": {
                            "summary": "No published schedule for this period (pointer missing "
                            "or published pointer is empty)",
                            "value": _err_example(
                                "not_found",
                                detail="not_found",
                                context={
                                    "where": "get_my_assignments.pointer_or_published_missing",
                                    "year": 2026,
                                    "month": 2,
                                    "doctor_id": 101,
                                    "has_pointer": False,
                                    "published_version_id": None,
                                },
                            ),
                        },
                        "published_version_missing": {
                            "summary": "Published pointer exists, but the pointed version row is missing",
                            "value": _err_example(
                                "not_found",
                                detail="not_found",
                                context={
                                    "where": "get_my_assignments.published_version_missing",
                                    "year": 2026,
                                    "month": 2,
                                    "doctor_id": 101,
                                    "published_version_id": 200,
                                },
                            ),
                        },
                    }
                }
            },
        },
        500: {
            "description": "Database error.",
            "content": {
                "application/json": {"example": _err_example("db_error", detail="Database error.", context={})}
            },
        },
    },
)
def schedules_my_assignments(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    user: UserCtx = Depends(require_doctor),
) -> MyAssignmentsRead:
    if user.doctor_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=make_error("forbidden"))
    try:
        return svc.get_my_assignments(year=year, month=month, doctor_id=int(user.doctor_id))
    except ValueError as e:
        _raise(e)
        assert False


# ---------------------- DOCTOR: my export -----------------------


export_svc = ExportService()


@router.get(
    "/{year}/{month}/my-export",
    tags=["schedules:doctor"],
    summary="Download my published schedule as XLSX, PDF, or ICS",
    responses={
        200: {
            "description": "Binary file download (xlsx, pdf, or ics).",
            "content": {
                "application/pdf": {},
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {},
                "text/calendar": {},
            },
        },
        404: {
            "description": "No published schedule for this period.",
            "content": {
                "application/json": {
                    "example": _err_example(
                        "not_found",
                        detail="not_found",
                        context={
                            "where": "export_my_schedule.no_published",
                            "year": 2026,
                            "month": 2,
                        },
                    )
                }
            },
        },
    },
)
def schedules_my_export(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    format: LiteralType["xlsx", "pdf", "ics"] = Query(...),
    user: UserCtx = Depends(require_doctor),
):
    if user.doctor_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=make_error("forbidden"),
        )
    try:
        result = export_svc.export_my_schedule(
            year=year,
            month=month,
            doctor_id=int(user.doctor_id),
            fmt=format,
        )
        return StreamingResponse(
            BytesIO(result.content),
            media_type=result.content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{result.filename}"',
            },
        )
    except ValueError as e:
        _raise(e)
        assert False


@router.get(
    "/{year}/{month}/team-export",
    tags=["schedules:doctor"],
    summary="Download full team published schedule as XLSX, PDF, or ICS",
    responses={
        200: {
            "description": "Binary file download (xlsx, pdf, or ics).",
            "content": {
                "application/pdf": {},
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {},
                "text/calendar": {},
            },
        },
        404: {
            "description": "No published schedule for this period.",
            "content": {
                "application/json": {
                    "example": _err_example(
                        "not_found",
                        detail="not_found",
                        context={
                            "where": "export_team_schedule.no_published",
                            "year": 2026,
                            "month": 2,
                        },
                    )
                }
            },
        },
    },
)
def schedules_team_export(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    format: LiteralType["xlsx", "pdf", "ics"] = Query(...),
    doctor_id: Optional[int] = Query(default=None, description="Filter by doctor"),
    shift_type: Optional[LiteralType["onsite", "oncall"]] = Query(default=None, description="Filter by shift type"),
    role: Optional[LiteralType["specialist", "resident"]] = Query(default=None, description="Filter by role"),
    user: UserCtx = Depends(require_doctor),
):
    try:
        result = export_svc.export_team_schedule(
            year=year,
            month=month,
            fmt=format,
            doctor_id=doctor_id,
            shift_type=shift_type,
            role=role,
        )
        return StreamingResponse(
            BytesIO(result.content),
            media_type=result.content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{result.filename}"',
            },
        )
    except ValueError as e:
        _raise(e)
        assert False


# ---------------------- DOCTOR: my diagnostics -------------------
@router.get(
    "/{year}/{month}/published/diagnostics/me",
    response_model=MyDoctorDiagnosticsRead,
    tags=["schedules:doctor"],
    summary="Get published per-doctor diagnostics for the current doctor (privacy-safe)",
    operation_id="schedules_published_my_diagnostics_get",
    description=(
        "Return published per-doctor diagnostics for the current doctor for {year, month}.\n\n"
        "Privacy:\n"
        "- Returns ONLY the current doctor's stats (totals, rest_violations, preference %, "
        "preferred_days_missed, ui_stars (1..5)).\n"
        "- No findings, no rankings, no audit, no other doctors.\n\n"
        "inputs_snapshot is required (NO FALLBACKS). If missing -> 409.\n"
    ),
    responses={
        200: {
            "description": "Doctor-facing diagnostics (only current doctor stats; no findings/rankings/audit).",
            "content": {
                "application/json": {
                    "examples": {
                        "ok": {
                            "summary": "Published per-doctor diagnostics for the current doctor",
                            "value": {
                                "version_id": 200,
                                "computed_at": "2026-01-28T10:05:01Z",
                                "doctor": {
                                    "doctor_id": 101,
                                    "display_name": "Doctor 101",
                                    "assigned_onsite_total": 5,
                                    "assigned_oncall_total": 3,
                                    "rest_violations": 0,
                                    "preferred_days_requested": 2,
                                    "preferred_days_missed": 2,
                                    "preference_fulfillment_pct": 82.0,
                                    "ui_stars": 4,
                                    "ui_reasons_codes": ["preferences_not_fully_met"],
                                    "categories": _example_categories(),
                                    "solver_components_by_doc": _example_solver_components_by_doc(),
                                },
                            },
                        },
                    }
                }
            },
        },
        403: {
            "description": "Forbidden (not a doctor account).",
            "content": {"application/json": {"example": _err_example("forbidden")}},
        },
        404: {
            "description": "Not found (published schedule missing or doctor not present in that snapshot).",
            "content": {
                "application/json": {
                    "examples": {
                        "published_missing": {
                            "summary": "No published schedule for this period",
                            "value": _err_example(
                                "not_found",
                                detail="Published schedule not found for this period.",
                                context={
                                    "where": "get_diagnostics.pointer_or_published_missing",
                                    "target": "published",
                                    "year": 2026,
                                    "month": 2,
                                },
                            ),
                        },
                        "doctor_not_in_snapshot": {
                            "summary": "Published schedule exists, but this doctor is not present in the snapshot",
                            "value": _err_example(
                                "not_found",
                                detail="Doctor not present in the published snapshot for this period.",
                                context={
                                    "where": "published_my_diagnostics.doctor_not_in_snapshot",
                                    "target": "published",
                                    "year": 2026,
                                    "month": 2,
                                    "doctor_id": 101,
                                    "version_id": 200,
                                },
                            ),
                        },
                    }
                }
            },
        },
        409: {
            "description": "Snapshot is required (NO FALLBACKS policy).",
            "content": {
                "application/json": {
                    "example": _err_example(
                        "diagnostics_requires_snapshot",
                        detail="Cannot compute diagnostics. Regenerate the schedule.",
                        context={"year": 2026, "month": 2, "version_id": 200},
                    )
                }
            },
        },
        500: {
            "description": "Database error.",
            "content": {
                "application/json": {"example": _err_example("db_error", detail="Server error. Try again.", context={})}
            },
        },
    },
)
def schedules_published_my_diagnostics(
    user: UserCtx = Depends(require_doctor),
    year: int = Path(..., ge=1900, le=2100, description="Calendar year"),
    month: int = Path(..., ge=1, le=12, description="Month 1..12"),
) -> MyDoctorDiagnosticsRead:
    """
    Doctor-facing diagnostics for published schedule.

    Returns ONLY:
    - totals (onsite/oncall),
    - rest_violations,
    - preference_fulfillment_pct,
    - preferred_days_missed,
    - optional score.

    No findings, no rankings, no audit.
    """
    if user.doctor_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=make_error("forbidden"))

    try:
        diag = svc.get_diagnostics(year=year, month=month, target="published")

        # Published must have a version_id.
        if diag.version_id is None:
            raise DomainError(
                "not_found",
                context={
                    "where": "published_my_diagnostics.published_missing",
                    "target": "published",
                    "year": int(year),
                    "month": int(month),
                },
            )

        details = diag.details
        if details is None:
            raise DomainError(
                "not_found",
                context={
                    "where": "published_my_diagnostics.details_missing",
                    "target": "published",
                    "year": int(year),
                    "month": int(month),
                    "version_id": int(diag.version_id),
                },
            )

        my_row = next((r for r in details.per_doctor if int(r.doctor_id) == int(user.doctor_id)), None)
        if my_row is None:
            # Doctor not included in this published snapshot.
            raise DomainError(
                "not_found",
                context={
                    "where": "published_my_diagnostics.doctor_not_in_snapshot",
                    "target": "published",
                    "year": int(year),
                    "month": int(month),
                    "version_id": int(diag.version_id),
                    "doctor_id": int(user.doctor_id),
                },
            )

        return MyDoctorDiagnosticsRead(
            version_id=int(diag.version_id),
            computed_at=diag.computed_at,
            doctor=my_row,
        )

    except ValueError as e:
        _raise(e)
        assert False
