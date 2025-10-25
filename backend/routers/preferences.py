# backend/routers/preferences.py
# Preferences (Admin & Doctor) + Availability (pre-flight) — MVP endpoints.

from datetime import datetime, timezone

from fastapi import APIRouter, Body, Path, Query, status

from backend.models.schemas import (
    AvailabilityDayRead,
    # Availability (co-located with preferences)
    AvailabilityOverviewRead,
    PreferenceAutosaveAck,
    PreferenceCheckpointCreated,
    PreferenceRevertRead,
    PreferencesDeadlinePut,
    PreferencesDeadlineRead,
    PreferencesSummaryRead,
    # Preferences (admin + doctor)
    PreferenceWorkingPut,
    PreferenceWorkingRead,
)

router = APIRouter(tags=["preferences"])


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------------------
# 3.2 Preferences (ADMIN) — Summary
# ------------------------------------------------------------------------------
@router.get(
    "/api/v1/preferences/summary",
    response_model=PreferencesSummaryRead,
    summary="Summary: who submitted vs who is missing",
)
def preferences_summary(
    year: int = Query(..., ge=1900, le=2100),
    month: int = Query(..., ge=1, le=12),
):
    # Stub: replace with service aggregation
    return {
        "year": year,
        "month": month,
        "submitted": [42, 7, 9],
        "missing": [11, 13, 21],
        "last_update_at": _now_utc(),
    }


# ------------------------------------------------------------------------------
# 3.2 Preferences (ADMIN) — Read + Working PUT + Checkpoint + Undo/Redo
# ------------------------------------------------------------------------------
@router.get(
    "/api/v1/preferences/{year}/{month}/{doctor_id}",
    response_model=PreferenceWorkingRead,
    summary="Read current form (working + pointer hints) — ADMIN",
)
def admin_read_working(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    doctor_id: int = Path(..., ge=1),
):
    # Stub: replace with service fetch (working + pointer hints)
    return {
        "doctor_id": doctor_id,
        "year": year,
        "month": month,
        "unavailable_duty_days": [],
        "unavailable_oncall_days": [],
        "preferred_duty_days": [],
        "preferred_oncall_days": [],
        "min_duties_weekdays": 0,
        "max_duties_weekdays": 999,
        "min_duties_weekends": 0,
        "max_duties_weekends": 999,
        "min_oncall_weekdays": 0,
        "max_oncall_weekdays": 999,
        "min_oncall_weekends": 0,
        "max_oncall_weekends": 999,
        "weekend_back_to_back_allowed": True,
        "preferred_partners": [],
        "comments": "",
        "status": "missing",
        "version_id": None,
        "submitted_at": None,
        "submitted_by_role": None,
        "submitted_by_user_id": None,
        "last_admin_note": None,
        "can_undo": False,
        "can_redo": False,
        "org_timezone": "Europe/Warsaw",
        "period_status": "current",
    }


@router.put(
    "/api/v1/preferences/{year}/{month}/{doctor_id}/working",
    response_model=PreferenceAutosaveAck,
    summary="Autosave working (no checkpoint) — ADMIN",
)
def admin_put_working(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    doctor_id: int = Path(..., ge=1),
    payload: PreferenceWorkingPut = Body(...),
):
    # Stub: replace with service update of preferences_working
    now = _now_utc()
    return {
        "doctor_id": doctor_id,
        "year": year,
        "month": month,
        "updated_at": now,
        "status": "missing",
        "version_id": None,
        "can_undo": False,
        "can_redo": False,
        "processed_at": now,
    }


@router.post(
    "/api/v1/preferences/{year}/{month}/{doctor_id}/checkpoint",
    response_model=PreferenceCheckpointCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Save (create checkpoint) — ADMIN",
)
def admin_create_checkpoint(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    doctor_id: int = Path(..., ge=1),
    body: dict = Body(default_factory=dict),
):
    # Stub: replace with service save (working -> versions checkpoint + pointer move)
    now = _now_utc()
    return {
        "doctor_id": doctor_id,
        "year": year,
        "month": month,
        "unavailable_duty_days": [7, 14],
        "unavailable_oncall_days": [8],
        "preferred_duty_days": [10, 11],
        "preferred_oncall_days": [12],
        "min_duties_weekdays": 2,
        "max_duties_weekdays": 6,
        "min_duties_weekends": 1,
        "max_duties_weekends": 2,
        "min_oncall_weekdays": 2,
        "max_oncall_weekdays": 4,
        "min_oncall_weekends": 0,
        "max_oncall_weekends": 2,
        "weekend_back_to_back_allowed": False,
        "preferred_partners": [7],
        "comments": "avoid Mondays",
        "status": "submitted",
        "version_id": "prefv_2026_02_doctor11_0001",
        "submitted_at": now,
        "submitted_by_user_id": 101,
        "submitted_by_role": "admin",
        "can_undo": True,
        "can_redo": False,
        "processed_at": now,
    }


@router.post(
    "/api/v1/preferences/{year}/{month}/{doctor_id}/revert-last",
    response_model=PreferenceRevertRead,
    summary="UNDO one checkpoint — ADMIN",
)
def admin_revert_last(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    doctor_id: int = Path(..., ge=1),
):
    # Stub: replace with service pointer move to previous + working overwrite
    now = _now_utc()
    return {
        "doctor_id": doctor_id,
        "year": year,
        "month": month,
        "unavailable_duty_days": [7, 14],
        "unavailable_oncall_days": [8],
        "preferred_duty_days": [10, 11],
        "preferred_oncall_days": [12],
        "min_duties_weekdays": 2,
        "max_duties_weekdays": 6,
        "min_duties_weekends": 1,
        "max_duties_weekends": 2,
        "min_oncall_weekdays": 2,
        "max_oncall_weekdays": 4,
        "min_oncall_weekends": 0,
        "max_oncall_weekends": 2,
        "weekend_back_to_back_allowed": False,
        "preferred_partners": [7],
        "comments": "avoid Mondays",
        "reverted_at": now,
        "version_id": "prefv_2026_02_doctor11_0000",
        "current_created_by_role": "admin",
        "current_created_by_user_id": 101,
        "current_created_at": now,
        "can_undo": True,
        "can_redo": True,
    }


@router.post(
    "/api/v1/preferences/{year}/{month}/{doctor_id}/revert-next",
    response_model=PreferenceRevertRead,
    summary="REDO one checkpoint — ADMIN",
)
def admin_revert_next(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    doctor_id: int = Path(..., ge=1),
):
    # Stub: replace with service pointer move to next + working overwrite
    now = _now_utc()
    return {
        "doctor_id": doctor_id,
        "year": year,
        "month": month,
        "unavailable_duty_days": [7, 14],
        "unavailable_oncall_days": [8],
        "preferred_duty_days": [10, 11],
        "preferred_oncall_days": [12],
        "min_duties_weekdays": 2,
        "max_duties_weekdays": 6,
        "min_duties_weekends": 1,
        "max_duties_weekends": 2,
        "min_oncall_weekdays": 2,
        "max_oncall_weekdays": 4,
        "min_oncall_weekends": 0,
        "max_oncall_weekends": 2,
        "weekend_back_to_back_allowed": False,
        "preferred_partners": [7],
        "comments": "avoid Mondays",
        "reverted_at": now,
        "version_id": "prefv_2026_02_doctor11_0001",
        "current_created_by_role": "admin",
        "current_created_by_user_id": 101,
        "current_created_at": now,
        "can_undo": True,
        "can_redo": False,
    }


# ------------------------------------------------------------------------------
# Deadlines (ADMIN) — GET / PUT-as-upsert
# ------------------------------------------------------------------------------
@router.get(
    "/api/v1/preferences/deadlines/{year}/{month}",
    response_model=PreferencesDeadlineRead,
    summary="Read deadline for a period",
)
def get_deadline(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
):
    # Stub: replace with service read
    return {
        "year": year,
        "month": month,
        "deadline": _now_utc(),
        "status": "open",
        "org_timezone": "Europe/Warsaw",
    }


@router.put(
    "/api/v1/preferences/deadlines/{year}/{month}",
    response_model=PreferencesDeadlinePut,
    summary="Create/Update deadline (PUT-as-upsert)",
)
def put_deadline(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    body: dict = Body(..., description='{"deadline": "2026-01-22T23:59:59Z"}'),
):
    # Stub: replace with service upsert
    return {
        "year": year,
        "month": month,
        "deadline": _now_utc(),
        "status": "open",
        "org_timezone": "Europe/Warsaw",
    }


# ------------------------------------------------------------------------------
# 4.1 Preferences (DOCTOR — own) — /me variants
# ------------------------------------------------------------------------------
@router.get(
    "/api/v1/preferences/{year}/{month}/me",
    response_model=PreferenceWorkingRead,
    summary="Read my preferences (working + hints) — DOCTOR",
)
def me_read_working(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
):
    # Stub: service infers doctor_id from token
    return admin_read_working(year=year, month=month, doctor_id=11)


@router.put(
    "/api/v1/preferences/{year}/{month}/me/working",
    response_model=PreferenceAutosaveAck,
    summary="Autosave my working — DOCTOR",
)
def me_put_working(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    payload: PreferenceWorkingPut = Body(...),
):
    # Stub: service infers doctor_id from token
    return admin_put_working(year=year, month=month, doctor_id=11, payload=payload)


@router.post(
    "/api/v1/preferences/{year}/{month}/me/checkpoint",
    response_model=PreferenceCheckpointCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Save (create checkpoint) — DOCTOR",
)
def me_create_checkpoint(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    body: dict = Body(default_factory=dict),
):
    # Stub: service infers doctor_id from token
    resp = admin_create_checkpoint(year=year, month=month, doctor_id=11, body=body)
    resp["submitted_by_role"] = "doctor"
    resp["submitted_by_user_id"] = 11
    return resp


@router.post(
    "/api/v1/preferences/{year}/{month}/me/revert-last",
    response_model=PreferenceRevertRead,
    summary="UNDO one checkpoint — DOCTOR",
)
def me_revert_last(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
):
    return admin_revert_last(year=year, month=month, doctor_id=11)


@router.post(
    "/api/v1/preferences/{year}/{month}/me/revert-next",
    response_model=PreferenceRevertRead,
    summary="REDO one checkpoint — DOCTOR",
)
def me_revert_next(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
):
    return admin_revert_next(year=year, month=month, doctor_id=11)


# ------------------------------------------------------------------------------
# 3.3 Availability (pre-flight) — colocated here
# ------------------------------------------------------------------------------
@router.get(
    "/api/v1/availability/overview",
    response_model=AvailabilityOverviewRead,
    summary="Monthly availability overview",
)
def availability_overview(
    year: int = Query(..., ge=1900, le=2100),
    month: int = Query(..., ge=1, le=12),
):
    # Stub: replace with service aggregation
    return {
        "days": [
            {"day": 1, "available_specialists": 5, "available_residents": 6, "risk": "ok"},
            {"day": 10, "available_specialists": 1, "available_residents": 1, "risk": "alert"},
            {"day": 12, "available_specialists": 0, "available_residents": 2, "risk": "critical"},
        ]
    }


@router.get(
    "/api/v1/availability/{year}/{month}/{day}",
    response_model=AvailabilityDayRead,
    summary="Day drill-down of availability",
)
def availability_day(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    day: int = Path(..., ge=1, le=31),
):
    # Stub: replace with service drill-down
    return {
        "day": day,
        "specialists": [],
        "residents": [{"id": 3, "first_name": "Ola", "last_name": "Nowicka"}],
        "risk": "critical",
    }
