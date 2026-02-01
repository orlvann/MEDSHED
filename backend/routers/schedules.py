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
- DiagnosticsRead.details is a typed structure (findings/per_doctor/rankings/audit/components).
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

from typing import Literal, Optional, cast

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status

from backend.core import issues
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
)
from backend.routers.deps import UserCtx, require_admin, require_doctor
from backend.services import SchedulingService

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
                                "per_doctor": [],
                                "rankings": {"top_unhappy": [], "top_happy": []},
                                "audit": [],
                                "components": {},
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
                                    "issues_total": 7,
                                    "issues_truncated": False,
                                    "issues_summary": [
                                        {"code": "no_oncall_candidate", "count": 3},
                                        {"code": "no_onsite_candidate", "count": 4},
                                    ],
                                    "issues_sample": [
                                        {"day": 3, "code": "no_onsite_candidate", "message": "no_onsite_candidate"},
                                        {"day": 3, "code": "no_oncall_candidate", "message": "no_oncall_candidate"},
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
                            "summary": "Working diagnostics (details contains working_lock_version)",
                            "value": {
                                "version_id": None,
                                "computed_at": "2026-01-28T09:20:00Z",
                                "summary": {
                                    "coverage_missing_required_slots": 2,
                                    "hard_issues_count": 1,
                                    "rest_violations": 0,
                                    "fairness_index": 0.93,
                                    "preference_fulfillment_pct": 78.0,
                                },
                                "details": {
                                    # IMPORTANT:
                                    # - There is NO COVERAGE_IGNORED_SLOT info finding anymore.
                                    # - We only mark actual missing slots with was_ignored=True/False.
                                    "findings": [
                                        {
                                            "code": _issue_code(issues.COVERAGE_MISSING_REQUIRED_SLOT),
                                            "severity": "critical",
                                            "context": {"day": 2, "shift_type": "onsite", "was_ignored": True},
                                        },
                                        {
                                            "code": _issue_code(issues.COVERAGE_MISSING_REQUIRED_SLOT),
                                            "severity": "critical",
                                            "context": {"day": 2, "shift_type": "oncall", "was_ignored": False},
                                        },
                                    ],
                                    "per_doctor": [
                                        {
                                            "doctor_id": 101,
                                            "display_name": "Doctor 101",
                                            "assigned_onsite_total": 5,
                                            "assigned_oncall_total": 3,
                                            "rest_violations": 0,
                                            "preference_fulfillment_pct": 78.0,
                                            "preferred_days_missed": 2,
                                            "score": -120.0,
                                        }
                                    ],
                                    "rankings": {
                                        "top_unhappy": [
                                            {
                                                "doctor_id": 101,
                                                "score": -120.0,
                                                "reasons_codes": ["preferred_days_missed", "preferences_not_fully_met"],
                                            }
                                        ],
                                        "top_happy": [
                                            {
                                                "doctor_id": 101,
                                                "score": -120.0,
                                                "reasons_codes": ["good_rest"],
                                            }
                                        ],
                                    },
                                    # Not forcing audit content in working.
                                    "audit": [],
                                    "components": {},
                                    "working_lock_version": 7,
                                },
                            },
                        },
                        "draft": {
                            "summary": "Draft diagnostics (version_id is checkpoint id)",
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
                                    "findings": [],
                                    "per_doctor": [],
                                    "rankings": {"top_unhappy": [], "top_happy": []},
                                    # Draft usually has no "human decision audit" rows.
                                    "audit": [],
                                    "components": {},
                                    "working_lock_version": None,
                                },
                            },
                        },
                        "published": {
                            "summary": "Published diagnostics (version_id is published version id)",
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
                                            "context": {"day": 10, "shift_type": "oncall", "was_ignored": False},
                                        }
                                    ],
                                    "per_doctor": [],
                                    "rankings": {"top_unhappy": [], "top_happy": []},
                                    # Example: a human accepted a hard violation during force publish.
                                    "audit": [
                                        {
                                            "code": _issue_code(issues.COVERAGE_MISSING_REQUIRED_SLOT),
                                            "justification": "Force publish: "
                                            "Duty shortage accepted for day 10 oncall.",
                                            "accepted_by_user_id": 1,
                                            "accepted_at": "2026-01-28T10:00:10Z",
                                        }
                                    ],
                                    "components": {},
                                    "working_lock_version": None,
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
                "application/json": {"example": _err_example("db_error", detail="Database error.", context={})}
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
                                        "findings": [],
                                        "per_doctor": [],
                                        "rankings": {"top_unhappy": [], "top_happy": []},
                                        "audit": [],
                                        "components": {},
                                        "working_lock_version": None,
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
                                        "findings": [],
                                        "per_doctor": [],
                                        "rankings": {"top_unhappy": [], "top_happy": []},
                                        "audit": [],
                                        "components": {},
                                        "working_lock_version": None,
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
def schedules_working_put(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    body: ScheduleWorkingPut = Body(...),
    user: UserCtx = Depends(require_admin),
) -> ScheduleWorkingAck:
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
                                "findings": [],
                                "per_doctor": [],
                                "rankings": {"top_unhappy": [], "top_happy": []},
                                "audit": [],
                                "components": {},
                                "working_lock_version": None,
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
                                "findings": [],
                                "per_doctor": [],
                                "rankings": {"top_unhappy": [], "top_happy": []},
                                "audit": [],
                                "components": {},
                                "working_lock_version": None,
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
                                "findings": [],
                                "per_doctor": [],
                                "rankings": {"top_unhappy": [], "top_happy": []},
                                "audit": [],
                                "components": {},
                                "working_lock_version": None,
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
            "description": "Not found (no published pointer/version).",
            "content": {"application/json": {"example": _err_example("not_found")}},
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
            "description": "Not found (no published pointer/version).",
            "content": {"application/json": {"example": _err_example("not_found")}},
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
    try:
        return svc.get_my_assignments(year=year, month=month, doctor_id=user.user_id if user else -1)
    except ValueError as e:
        _raise(e)
        assert False
