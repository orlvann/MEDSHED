# backend/routers/preferences.py
# This router exposes the monthly preference form lifecycle for Doctors and Admins.
# - GET /api/v1/preferences?year&month            -> current user (doctor) view
# - GET /api/v1/preferences/{doctor_id}?year&month-> admin view of a doctor's form
# - POST /api/v1/preferences                       -> create/replace (upsert) a form
# - PATCH /api/v1/preferences/{pref_id}            -> partial update (doctor before deadline or admin override)
# - POST /api/v1/preferences/{pref_id}/submit      -> mark as SUBMITTED (still editable until deadline)
# - POST /api/v1/preferences/{pref_id}/revert      -> revert to DRAFT (before deadline)
# - GET /api/v1/preferences/{pref_id}/audit        -> list audit trail entries
#
# Notes:
# * Deadline & RBAC (role-based access control) are enforced in the service layer.
# * When a doctor edits their already SUBMITTED form before the deadline, service should flip status back to DRAFT.
# * Admin edits should be recorded with who/when (audit trail).
# * Response models are strict Pydantic DTOs, so Swagger shows correct shapes from day one.

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Path, Query, status

from backend.models.schemas import (
    PreferenceAuditEntryRead,
    PreferenceCreate,
    PreferenceRead,
    PreferenceStatus,
    PreferenceSummary,
    PreferenceUpdate,
)

router = APIRouter(tags=["preferences"])

# --- Helpers for mock timestamps ------------------------------------------------


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Endpoints ------------------------------------------------------------------


@router.get(
    "/api/v1/preferences",
    response_model=PreferenceRead,
    summary="Get my monthly preferences (doctor)",
)
def get_preferences(
    year: int = Query(..., ge=1900, le=2100, description="Calendar year"),
    month: int = Query(..., ge=1, le=12, description="1..12"),
    doctor_id: Optional[int] = Query(
        None,
        description="Admin only: fetch another doctor's form. If omitted, infer from auth.",
    ),
):
    # TODO:
    # - if doctor_id is None -> use current_user.id
    # - enforce RBAC: only ADMIN can pass doctor_id != current_user.id
    # - preference_service.get(doctor_id, year, month)
    return {
        "id": 123,
        "doctor_id": doctor_id or 1,
        "year": year,
        "month": month,
        "unavailable_duty_days": [7, 14],
        "preferred_duty_days": [10, 11],
        "unavailable_oncall_days": [8],
        "preferred_oncall_days": [12],
        "min_duties_weekdays": 5,
        "max_duties_weekdays": 7,
        "min_duties_weekends": 2,
        "max_duties_weekends": 3,
        "min_oncall_weekdays": 3,
        "max_oncall_weekdays": 5,
        "min_oncall_weekends": 1,
        "max_oncall_weekends": 2,
        "weekend_back_to_back_allowed": False,
        "preferred_partners": [2, 3],
        "comments": "No nights after clinics",
        # lifecycle & audit
        "status": PreferenceStatus.DRAFT,
        "submitted_at": None,
        "updated_at": _now_utc_iso(),
        "updated_by_user_id": 1,
    }


@router.get(
    "/api/v1/preferences/{doctor_id}",
    response_model=PreferenceRead,
    summary="Get a doctor's monthly preferences (admin)",
)
def get_preferences_for_doctor(
    doctor_id: int = Path(..., ge=1),
    year: int = Query(..., ge=1900, le=2100),
    month: int = Query(..., ge=1, le=12),
):
    # TODO:
    # - enforce RBAC: ADMIN only
    # - preference_service.get(doctor_id, year, month)
    return {
        "id": 124,
        "doctor_id": doctor_id,
        "year": year,
        "month": month,
        "unavailable_duty_days": [],
        "preferred_duty_days": [],
        "unavailable_oncall_days": [],
        "preferred_oncall_days": [],
        "min_duties_weekdays": 0,
        "max_duties_weekdays": None,
        "min_duties_weekends": 0,
        "max_duties_weekends": None,
        "min_oncall_weekdays": 0,
        "max_oncall_weekdays": None,
        "min_oncall_weekends": 0,
        "max_oncall_weekends": None,
        "weekend_back_to_back_allowed": False,
        "preferred_partners": [],
        "comments": None,
        "status": PreferenceStatus.SUBMITTED,
        "submitted_at": _now_utc_iso(),
        "updated_at": _now_utc_iso(),
        "updated_by_user_id": 9,  # previous editor
    }


@router.post(
    "/api/v1/preferences",
    response_model=PreferenceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create or replace monthly preferences (upsert)",
)
def upsert_preferences(payload: PreferenceCreate = Body(...)):
    # TODO:
    # - Only the owner doctor or ADMIN can upsert for (doctor_id).
    # - If a record exists -> replace contents (or soft-merge by service policy).
    # - Record audit entry (action='create' | 'update').
    # - Keep status rules: if upsert by doctor before deadline -> likely DRAFT/SUBMITTED.
    return {
        "id": 125,
        **payload.model_dump(),
        "status": PreferenceStatus.DRAFT,
        "submitted_at": None,
        "updated_at": _now_utc_iso(),
        "updated_by_user_id": payload.doctor_id,  # mock: self-edit
    }


@router.patch(
    "/api/v1/preferences/{pref_id}",
    response_model=PreferenceRead,
    summary="Partial update monthly preferences",
)
def patch_preferences(
    pref_id: int = Path(..., ge=1),
    payload: PreferenceUpdate = Body(...),
):
    # TODO (service responsibilities):
    # - Load existing pref by id; check authorizations.
    # - If editor is DOCTOR and before deadline:
    #     * apply partial fields
    #     * if current status == SUBMITTED -> flip to DRAFT (editable)
    # - If editor is ADMIN:
    #     * apply partial fields
    #     * may keep or change status (override)
    # - Save + write audit entry (action='update' or 'admin_override')
    base = {
        "id": pref_id,
        "doctor_id": 1,
        "year": 2026,
        "month": 2,
        "unavailable_duty_days": [7],
        "unavailable_oncall_days": [],
        "preferred_duty_days": [10],
        "preferred_oncall_days": [],
        "min_duties_weekdays": 2,
        "max_duties_weekdays": 4,
        "min_duties_weekends": 1,
        "max_duties_weekends": 2,
        "min_oncall_weekdays": 1,
        "max_oncall_weekdays": 3,
        "min_oncall_weekends": 0,
        "max_oncall_weekends": 1,
        "weekend_back_to_back_allowed": False,
        "preferred_partners": [],
        "comments": None,
        "status": PreferenceStatus.DRAFT,  # mock: assume edit flipped from SUBMITTED -> DRAFT
        "submitted_at": None,
        "updated_at": _now_utc_iso(),
        "updated_by_user_id": 1,
    }
    return {**base, **payload.model_dump(exclude_unset=True)}


@router.post(
    "/api/v1/preferences/{pref_id}/submit",
    response_model=PreferenceRead,
    summary="Mark preferences as SUBMITTED (still editable until deadline)",
)
def submit_preferences(pref_id: int = Path(..., ge=1)):
    # TODO:
    # - Doctor or Admin can submit.
    # - If after deadline -> service should reject (422) or auto LOCK (policy decision).
    # - preference_service.submit(pref_id, actor_id)
    return {
        "id": pref_id,
        "doctor_id": 1,
        "year": 2026,
        "month": 2,
        "unavailable_duty_days": [7],
        "unavailable_oncall_days": [],
        "preferred_duty_days": [10],
        "preferred_oncall_days": [],
        "min_duties_weekdays": 2,
        "max_duties_weekdays": 4,
        "min_duties_weekends": 1,
        "max_duties_weekends": 2,
        "min_oncall_weekdays": 1,
        "max_oncall_weekdays": 3,
        "min_oncall_weekends": 0,
        "max_oncall_weekends": 1,
        "weekend_back_to_back_allowed": False,
        "preferred_partners": [],
        "comments": None,
        "status": PreferenceStatus.SUBMITTED,
        "submitted_at": _now_utc_iso(),
        "updated_at": _now_utc_iso(),
        "updated_by_user_id": 1,
    }


@router.post(
    "/api/v1/preferences/{pref_id}/revert",
    response_model=PreferenceRead,
    summary="Revert SUBMITTED back to DRAFT (before deadline)",
)
def revert_preferences(pref_id: int = Path(..., ge=1)):
    # TODO:
    # - Doctor can revert before deadline; Admin can revert anytime (override).
    # - preference_service.revert(pref_id, actor_id)
    return {
        "id": pref_id,
        "doctor_id": 1,
        "year": 2026,
        "month": 2,
        "unavailable_duty_days": [7],
        "unavailable_oncall_days": [],
        "preferred_duty_days": [10],
        "preferred_oncall_days": [],
        "min_duties_weekdays": 2,
        "max_duties_weekdays": 4,
        "min_duties_weekends": 1,
        "max_duties_weekends": 2,
        "min_oncall_weekdays": 1,
        "max_oncall_weekdays": 3,
        "min_oncall_weekends": 0,
        "max_oncall_weekends": 1,
        "weekend_back_to_back_allowed": False,
        "preferred_partners": [],
        "comments": None,
        "status": PreferenceStatus.DRAFT,
        "submitted_at": None,
        "updated_at": _now_utc_iso(),
        "updated_by_user_id": 1,
    }


@router.get(
    "/api/v1/preferences/{pref_id}/audit",
    response_model=list[PreferenceAuditEntryRead],
    summary="List audit entries for a preference form",
)
def preferences_audit(pref_id: int = Path(..., ge=1)):
    # TODO:
    # - Admin or owner doctor can view audit log.
    # - preference_service.audit(pref_id)
    return [
        {
            "id": 1,
            "preference_id": pref_id,
            "actor_user_id": 1,
            "actor_role": "DOCTOR",
            "action": "create",
            "at": _now_utc_iso(),
            "diff": {"created": True},
        },
        {
            "id": 2,
            "preference_id": pref_id,
            "actor_user_id": 9,
            "actor_role": "ADMIN",
            "action": "admin_override",
            "at": _now_utc_iso(),
            "diff": {"preferred_duty_days": [10, 11]},
        },
    ]


@router.get(
    "/api/v1/preferences/summary",
    response_model=PreferenceSummary,
    summary="Submission & coverage summary",
)
def preferences_summary(
    year: int = Query(..., ge=1900, le=2100),
    month: int = Query(..., ge=1, le=12),
):
    # TODO:
    # - Admin only; aggregate who submitted vs missing
    # - coverage per day for OnDuty/OnCall (availability count)
    # - preference_service.summary(year, month)
    return {
        "submitted": [1, 2, 3],
        "missing": [5, 7],
        "coverageByDay": [{"day": 1, "availableDuty": 5, "availableOnCall": 3}],
    }
