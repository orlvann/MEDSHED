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
- DiagnosticsRead.details is a legacy free JSON dict (service fills THIS today).
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
    ScheduleWorkingRead,
)
from backend.routers.deps import UserCtx, require_admin, require_doctor
from backend.services import SchedulingService

router = APIRouter(prefix="/api/v1/schedules")
svc = SchedulingService()


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
        "generate_requires_ignore": status.HTTP_409_CONFLICT,
        "generate_requires_head_resolution": status.HTTP_409_CONFLICT,
        "generate_infeasible": status.HTTP_409_CONFLICT,
        "db_integrity_error": status.HTTP_500_INTERNAL_SERVER_ERROR,
        "db_error": status.HTTP_500_INTERNAL_SERVER_ERROR,
    }

    human_detail = {
        "generate_requires_ignore": "Generation requires ignore_slots to proceed.",
        "generate_requires_head_resolution": "Generation requires choosing a head for conflicting commitment slots.",
        "generate_infeasible": "Generation failed: solver could not find a feasible solution.",
        "invalid_head_commitment_resolution": "Invalid head commitment resolution payload.",
        "publish_blocked_by_hard_rules": "Publishing blocked: hard rule violations detected.",
        "db_integrity_error": "Database integrity error.",
        "db_error": "Database error.",
    }

    if code in mapping:
        context = getattr(e, "context", None)
        if not isinstance(context, dict):
            context = {}

        detail = human_detail.get(code) or getattr(e, "detail", None) or code

        raise HTTPException(
            status_code=mapping[code],
            detail=make_error(code, detail=detail, context=context),
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
                            "meta": {"labels": ["as_generated"], "solver_status": "OK", "exceptions": []},
                            "updated_at": "2026-01-28T09:15:00Z",
                            "lock_version": 2,
                            "inputs_snapshot": {
                                # NOTE: JSON object keys are strings; InputsSnapshotRead will coerce to int.
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
                                "meta": {"labels": ["as_generated"], "solver_status": "OK", "exceptions": []},
                            },
                        },
                        "diagnostics": {
                            "version_id": "123",
                            "computed_at": "2026-01-28T09:15:01Z",
                            "summary": {
                                "coverage_missing_required_slots": 0,
                                "hard_issues_count": 0,
                                "rest_violations": 0,
                                "fairness_index": 1.0,
                                "preference_fulfillment_pct": 100.0,
                            },
                            # Service currently fills legacy free dict:
                            "details": {
                                "findings": [],
                                "per_doctor": [],
                                "rankings": {"top_unhappy": [], "top_happy": []},
                                "working_lock_version": None,
                            },
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
                        "requires_ignore_slots": {
                            "summary": "Feasibility pre-check: requires ignore_slots",
                            "value": _err_example(
                                "generate_requires_ignore",
                                detail="Generation requires ignore_slots to proceed.",
                                context={
                                    "year": 2026,
                                    "month": 2,
                                    "issues_total": 2,
                                    "issues_truncated": False,
                                    "issues_summary": [
                                        {"code": issues.NO_SPECIALIST, "count": 1},
                                        {"code": issues.NO_ONSITE_CANDIDATE, "count": 1},
                                    ],
                                    "issues_sample": [
                                        {
                                            "day": 3,
                                            "code": issues.NO_SPECIALIST,
                                            "message": "No specialist is available on this day.",
                                        },
                                        {
                                            "day": 3,
                                            "code": issues.NO_ONSITE_CANDIDATE,
                                            "message": "No doctor is available for onsite duty on this day.",
                                        },
                                    ],
                                },
                            ),
                        },
                        "requires_head_resolution": {
                            "summary": "Head commitments conflict: admin must resolve",
                            "value": _err_example(
                                "generate_requires_head_resolution",
                                detail="Generation requires choosing a head for conflicting commitment slots.",
                                context={
                                    "year": 2026,
                                    "month": 2,
                                    "head_commitment_conflicts": [
                                        {
                                            "day": 3,
                                            "shift_type": "onsite",
                                            "head_candidates": [
                                                {"doctor_id": 101, "display_name": "Jan Kowalski"},
                                                {"doctor_id": 110, "display_name": "Doctor 110"},
                                            ],
                                        }
                                    ],
                                },
                            ),
                        },
                        "infeasible": {
                            "summary": "Solver infeasible / not OK",
                            "value": _err_example(
                                "generate_infeasible",
                                detail="Generation failed: solver could not find a feasible solution.",
                                context={
                                    "year": 2026,
                                    "month": 2,
                                    "solver_status": "INFEASIBLE",
                                    "issues_total": 1,
                                    "issues_truncated": False,
                                    "issues_summary": [{"code": issues.CP_INFEASIBLE, "count": 1}],
                                    "issues_sample": [
                                        {
                                            "day": 0,
                                            "code": issues.CP_INFEASIBLE,
                                            "message": "No schedule satisfies all hard constraints for this month"
                                            "(CP-SAT infeasible).",
                                        }
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
                        "db_integrity_error": {
                            "summary": "Database integrity error",
                            "value": _err_example("db_integrity_error", detail="Database integrity error.", context={}),
                        },
                        "db_error": {
                            "summary": "Database error",
                            "value": _err_example("db_error", detail="Database error.", context={}),
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
                                "version_id": "working",
                                "computed_at": "2026-01-28T09:20:00Z",
                                "summary": {
                                    "coverage_missing_required_slots": 2,
                                    "hard_issues_count": 1,
                                    "rest_violations": 0,
                                    "fairness_index": 0.93,
                                    "preference_fulfillment_pct": 78.0,
                                },
                                # Service fills legacy dict today:
                                "details": {
                                    "findings": [
                                        {
                                            "code": issues.COVERAGE_IGNORED_SLOT,
                                            "severity": "info",
                                            "context": {"day": 2, "shift_type": "onsite"},
                                        },
                                        {
                                            "code": issues.COVERAGE_MISSING_REQUIRED_SLOT,
                                            "severity": "critical",
                                            "context": {"day": 2, "shift_type": "onsite", "was_ignored": True},
                                        },
                                        {
                                            "code": issues.COVERAGE_MISSING_REQUIRED_SLOT,
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
                                    "working_lock_version": 7,
                                },
                            },
                        },
                        "draft": {
                            "summary": "Draft diagnostics (version_id is checkpoint id)",
                            "value": {
                                "version_id": "123",
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
                                    "working_lock_version": None,
                                },
                            },
                        },
                        "published": {
                            "summary": "Published diagnostics (version_id is published version id)",
                            "value": {
                                "version_id": "200",
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
                                            "code": issues.COVERAGE_MISSING_REQUIRED_SLOT,
                                            "severity": "critical",
                                            "context": {"day": 10, "shift_type": "oncall", "was_ignored": False},
                                        }
                                    ],
                                    "per_doctor": [],
                                    "rankings": {"top_unhappy": [], "top_happy": []},
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
                                "view": {"default_mode": "draft", "toggle_available": True},
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
                                    "inputs_snapshot": None,
                                },
                                "draft": {
                                    "version_id": "124",
                                    "checkpoints_count": 2,
                                    "can_undo": True,
                                    "can_redo": False,
                                    "payload": {
                                        "participant_doctor_ids": [101, 102, 103],
                                        "assignments": [{"day": 1, "shift_type": "onsite", "doctor_id": 101}],
                                        "inputs_snapshot": None,
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
                                    "version_id": "124",
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
    responses={
        200: {
            "description": "Working buffer (or skeleton if it doesn't exist).",
            "content": {
                "application/json": {
                    "examples": {
                        "exists_false": {
                            "summary": "No working row yet",
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
                        "exists_true": {
                            "summary": "Working exists",
                            "value": {
                                "year": 2026,
                                "month": 2,
                                "exists": True,
                                "participant_doctor_ids": [101, 102, 103],
                                "assignments": [{"day": 1, "shift_type": "onsite", "doctor_id": 101}],
                                "meta": {"labels": []},
                                "updated_at": "2026-01-28T09:30:00Z",
                                "lock_version": 8,
                                "inputs_snapshot": None,
                            },
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
def schedules_working_read(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    user: UserCtx = Depends(require_admin),
) -> ScheduleWorkingRead:
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
    responses={
        200: {
            "description": "Working saved; lock_version may be bumped.",
            "content": {
                "application/json": {
                    "example": {"year": 2026, "month": 2, "updated_at": "2026-01-28T09:30:00Z", "lock_version": 8}
                }
            },
        },
        409: {
            "description": "OCC conflict (if_match_lock_version mismatched) or similar edit conflict.",
            "content": {"application/json": {"example": _err_example("edit_conflict")}},
        },
        500: {
            "description": "Database errors (unexpected).",
            "content": {
                "application/json": {
                    "examples": {
                        "db_integrity_error": {
                            "summary": "Database integrity error",
                            "value": _err_example("db_integrity_error", detail="Database integrity error.", context={}),
                        },
                        "db_error": {
                            "summary": "Database error",
                            "value": _err_example("db_error", detail="Database error.", context={}),
                        },
                    }
                }
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
    responses={
        201: {
            "description": "Draft checkpoint created from working; diagnostics computed.",
            "content": {
                "application/json": {
                    "example": {
                        "year": 2026,
                        "month": 2,
                        "draft": {
                            "version_id": "124",
                            "checkpoints_count": 2,
                            "can_undo": True,
                            "can_redo": False,
                            "payload": {
                                "participant_doctor_ids": [101, 102, 103],
                                "assignments": [
                                    {"day": 1, "shift_type": "onsite", "doctor_id": 101},
                                    {"day": 1, "shift_type": "oncall", "doctor_id": 102},
                                ],
                                "inputs_snapshot": None,
                                "meta": {"labels": []},
                            },
                        },
                        "diagnostics": {
                            "version_id": "124",
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
    responses={
        200: {
            "description": "Draft pointer moved to previous checkpoint; working overwritten; diagnostics returned.",
            "content": {
                "application/json": {
                    "example": {
                        "year": 2026,
                        "month": 2,
                        "draft": {
                            "version_id": "120",
                            "checkpoints_count": 5,
                            "can_undo": True,
                            "can_redo": True,
                            "payload": None,
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
                            "inputs_snapshot": None,
                        },
                        "diagnostics": {
                            "version_id": "120",
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
                                "working_lock_version": None,
                            },
                        },
                    }
                }
            },
        },
        409: {
            "description": "No earlier version available.",
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
    responses={
        200: {
            "description": "Draft pointer moved to next checkpoint; working overwritten; diagnostics returned.",
            "content": {
                "application/json": {
                    "example": {
                        "year": 2026,
                        "month": 2,
                        "draft": {
                            "version_id": "121",
                            "checkpoints_count": 5,
                            "can_undo": True,
                            "can_redo": True,
                            "payload": None,
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
                            "inputs_snapshot": None,
                        },
                        "diagnostics": {
                            "version_id": "121",
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
                                "working_lock_version": None,
                            },
                        },
                    }
                }
            },
        },
        409: {
            "description": "No later version available.",
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
    summary="Publish from working (hard-rule guard; force supported)",
    responses={
        201: {
            "description": "Published version created from working.",
            "content": {
                "application/json": {
                    "example": {
                        "year": 2026,
                        "month": 2,
                        "published": {
                            "version_id": "200",
                            "publications_count": 1,
                            "can_undo": False,
                            "can_redo": False,
                            "audit": {
                                "published_at": "2026-01-28T10:00:00Z",
                                "published_by_user_id": 1,
                                "note": "Finalize",
                            },
                            "payload": None,
                        },
                    }
                }
            },
        },
        409: {
            "description": "Publishing blocked by hard-rule violations (unless force=True).",
            "content": {
                "application/json": {
                    "example": _err_example(
                        "publish_blocked_by_hard_rules",
                        detail="Publishing blocked: hard rule violations detected.",
                        context={
                            "year": 2026,
                            "month": 2,
                            "hard_violations": [
                                {
                                    "code": issues.COVERAGE_MISSING_REQUIRED_SLOT,
                                    "message": "Required coverage slot is missing.",
                                    "context": {"day": 10, "shift_type": "oncall", "was_ignored": False},
                                }
                            ],
                            "diagnostics_summary": {
                                "coverage_missing_required_slots": 1,
                                "hard_issues_count": 1,
                                "rest_violations": 0,
                                "fairness_index": 0.95,
                                "preference_fulfillment_pct": 82.0,
                            },
                            "generation_exceptions": [
                                {"code": issues.COVERAGE_IGNORED_SLOT, "day": 2, "shift_type": "onsite"},
                            ],
                        },
                    )
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
    responses={
        200: {
            "description": "Published pointer moved to previous published version (does not touch working).",
            "content": {
                "application/json": {
                    "example": {
                        "year": 2026,
                        "month": 2,
                        "published": {
                            "version_id": "199",
                            "publications_count": 2,
                            "can_undo": False,
                            "can_redo": True,
                            "audit": None,
                            "payload": None,
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
    responses={
        200: {
            "description": "Published pointer moved to next published version (does not touch working).",
            "content": {
                "application/json": {
                    "example": {
                        "year": 2026,
                        "month": 2,
                        "published": {
                            "version_id": "200",
                            "publications_count": 2,
                            "can_undo": True,
                            "can_redo": False,
                            "audit": None,
                            "payload": None,
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
                            "version_id": "200",
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
                                "inputs_snapshot": None,
                                "meta": {"labels": []},
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
