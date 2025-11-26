# backend/routers/preferences.py
# Preferences (Admin & Doctor) — unified router with RBAC, error shape, and clean Swagger.
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status

from backend.models.schemas import (
    PreferenceAutosaveAck,
    PreferenceCheckpointCreated,
    PreferenceRevertRead,
    PreferencesDeadlinePut,
    PreferencesDeadlineRead,
    PreferencesSummaryRead,
    PreferenceWorkingPut,
    PreferenceWorkingRead,
)
from backend.models.schemas.dto_common import MonthInt, YearInt, make_error
from backend.routers.deps import UserCtx, require_admin, require_doctor, require_user
from backend.services.preference_service import (
    create_checkpoint,
    get_deadline,
    get_working,
    is_doctor_locked_for_period,
    read_summary,
    revert_last,
    revert_next,
    save_working_autosave,
    upsert_deadline,
)
from backend.utils.timez import is_period_closed

router: APIRouter = APIRouter()


def _guard_period_closed(year: int, month: int) -> None:
    """
    Central guard: blocks write operations for past periods (org TZ).
    Contract choice: we return 409 'period_closed' (consistent with schedules/preferences).
    """
    if is_period_closed(year, month):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=make_error(
                "period_closed",
                detail="preferences for this past period are closed",
                context={"year": year, "month": month},
            ),
        )


def _guard_doctor_preferences_locked(year: int, month: int, user: UserCtx) -> None:
    """
    Guard for doctor-facing write endpoints (/me/...).

    Blocks edits when:
    - the period is already 'past' (history lock), OR
    - the configured deadline for this period has passed.

    Admin does NOT use this guard — admins can edit after deadline
    but still cannot change past periods (history lock via _guard_period_closed).
    """
    if is_doctor_locked_for_period(year=year, month=month, doctor_id=user.user_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=make_error(
                "period_closed",  # you can later rename to 'deadline_passed' if you want
                detail="preferences for this period are locked for doctor",
                context={"year": year, "month": month},
            ),
        )


# ------------------------------------------------------------------------------
# Deadlines — shared read (admin + doctor) + admin upsert
# ------------------------------------------------------------------------------
@router.get(
    "/api/v1/preferences/deadlines/{year}/{month}",
    response_model=PreferencesDeadlineRead,
    tags=["preferences:admin", "preferences:doctor"],
    summary="Read deadline for a period",
    operation_id="preferences_deadline_get",
)
def deadline_get(
    user: UserCtx = Depends(require_user),  # any authenticated user: admin or doctor
    year: YearInt = Path(...),
    month: MonthInt = Path(...),
):
    return get_deadline(year=year, month=month, actor=user)


@router.put(
    "/api/v1/preferences/deadlines/{year}/{month}",
    response_model=PreferencesDeadlinePut,
    tags=["preferences:admin"],
    summary="Create/Update deadline (upsert)",
    operation_id="preferences_admin_deadline_put",
)
def deadline_put(
    user: UserCtx = Depends(require_admin),
    year: YearInt = Path(...),
    month: MonthInt = Path(...),
    body: dict = Body(..., description='{"deadline": "2026-01-22T23:59:59Z"} (org tz aware in BE)'),
):
    return upsert_deadline(year=year, month=month, body=body, actor=user)


# ------------------------------------------------------------------------------
# Preferences (ADMIN) — Summary
# ------------------------------------------------------------------------------
@router.get(
    "/api/v1/preferences/summary",
    response_model=PreferencesSummaryRead,
    tags=["preferences:admin"],
    summary="Who submitted vs. who is missing",
    operation_id="preferences_admin_summary_get",
)
def preferences_summary(
    user: UserCtx = Depends(require_admin),
    year: YearInt = Query(...),
    month: MonthInt = Query(...),
):
    return read_summary(year=year, month=month, actor=user)


# ------------------------------------------------------------------------------
# 4.1 Preferences (DOCTOR — own) — /me variants
# ------------------------------------------------------------------------------
@router.get(
    "/api/v1/preferences/{year}/{month}/me",
    response_model=PreferenceWorkingRead,
    tags=["preferences:doctor"],
    summary="Read my preferences (working + hints)",
    operation_id="preferences_doctor_me_working_get",
)
def me_read_working(
    user: UserCtx = Depends(require_doctor),
    year: YearInt = Path(...),
    month: MonthInt = Path(...),
):
    doctor_id = user.user_id
    return get_working(year=year, month=month, doctor_id=doctor_id, actor=user)


@router.put(
    "/api/v1/preferences/{year}/{month}/me/working",
    response_model=PreferenceAutosaveAck,
    tags=["preferences:doctor"],
    summary="Autosave my working (no checkpoint)",
    operation_id="preferences_doctor_me_working_put",
)
def me_put_working(
    user: UserCtx = Depends(require_doctor),
    year: YearInt = Path(...),
    month: MonthInt = Path(...),
    payload: PreferenceWorkingPut = Body(...),
):
    # Doctor-specific lock: history + deadline.
    _guard_doctor_preferences_locked(year, month, user)

    doctor_id = user.user_id
    return save_working_autosave(year=year, month=month, doctor_id=doctor_id, payload=payload, actor=user)


@router.post(
    "/api/v1/preferences/{year}/{month}/me/checkpoint",
    response_model=PreferenceCheckpointCreated,
    status_code=status.HTTP_201_CREATED,
    tags=["preferences:doctor"],
    summary="Save (create checkpoint)",
    operation_id="preferences_doctor_me_checkpoint_post",
)
def me_create_checkpoint(
    user: UserCtx = Depends(require_doctor),
    year: YearInt = Path(...),
    month: MonthInt = Path(...),
    body: dict = Body(default_factory=dict),
):
    # Doctor-specific lock: history + deadline.
    _guard_doctor_preferences_locked(year, month, user)

    doctor_id = user.user_id
    return create_checkpoint(year=year, month=month, doctor_id=doctor_id, actor=user)


@router.post(
    "/api/v1/preferences/{year}/{month}/me/revert-last",
    response_model=PreferenceRevertRead,
    tags=["preferences:doctor"],
    summary="UNDO one checkpoint",
    operation_id="preferences_doctor_me_revert_last_post",
)
def me_revert_last(
    user: UserCtx = Depends(require_doctor),
    year: YearInt = Path(...),
    month: MonthInt = Path(...),
):
    # Doctor-specific lock: history + deadline.
    _guard_doctor_preferences_locked(year, month, user)

    doctor_id = user.user_id
    return revert_last(year=year, month=month, doctor_id=doctor_id, actor=user)


@router.post(
    "/api/v1/preferences/{year}/{month}/me/revert-next",
    response_model=PreferenceRevertRead,
    tags=["preferences:doctor"],
    summary="REDO one checkpoint",
    operation_id="preferences_doctor_me_revert_next_post",
)
def me_revert_next(
    user: UserCtx = Depends(require_doctor),
    year: YearInt = Path(...),
    month: MonthInt = Path(...),
):
    # Doctor-specific lock: history + deadline.
    _guard_doctor_preferences_locked(year, month, user)

    doctor_id = user.user_id
    return revert_next(year=year, month=month, doctor_id=doctor_id, actor=user)


# ------------------------------------------------------------------------------
# 3.2 Preferences (ADMIN) — Read + Working PUT + Checkpoint + Undo/Redo
# ------------------------------------------------------------------------------
@router.get(
    "/api/v1/preferences/{year}/{month}/{doctor_id}",
    response_model=PreferenceWorkingRead,
    tags=["preferences:admin"],
    summary="Read current form (working + hints)",
    operation_id="preferences_admin_working_get",
)
def admin_read_working(
    user: UserCtx = Depends(require_admin),
    year: YearInt = Path(...),
    month: MonthInt = Path(...),
    doctor_id: int = Path(..., ge=1),
):
    return get_working(year=year, month=month, doctor_id=doctor_id, actor=user)


@router.put(
    "/api/v1/preferences/{year}/{month}/{doctor_id}/working",
    response_model=PreferenceAutosaveAck,
    tags=["preferences:admin"],
    summary="Autosave working (no checkpoint)",
    operation_id="preferences_admin_working_put",
)
def admin_put_working(
    user: UserCtx = Depends(require_admin),
    year: YearInt = Path(...),
    month: MonthInt = Path(...),
    doctor_id: int = Path(..., ge=1),
    payload: PreferenceWorkingPut = Body(...),
):
    _guard_period_closed(year, month)
    return save_working_autosave(year=year, month=month, doctor_id=doctor_id, payload=payload, actor=user)


@router.post(
    "/api/v1/preferences/{year}/{month}/{doctor_id}/checkpoint",
    response_model=PreferenceCheckpointCreated,
    status_code=status.HTTP_201_CREATED,
    tags=["preferences:admin"],
    summary="Save (create checkpoint)",
    operation_id="preferences_admin_checkpoint_post",
)
def admin_create_checkpoint(
    user: UserCtx = Depends(require_admin),
    year: YearInt = Path(...),
    month: MonthInt = Path(...),
    doctor_id: int = Path(..., ge=1),
    body: dict = Body(default_factory=dict),
):
    _guard_period_closed(year, month)
    # body reserved for future flags
    return create_checkpoint(year=year, month=month, doctor_id=doctor_id, actor=user)


@router.post(
    "/api/v1/preferences/{year}/{month}/{doctor_id}/revert-last",
    response_model=PreferenceRevertRead,
    tags=["preferences:admin"],
    summary="UNDO one checkpoint",
    operation_id="preferences_admin_revert_last_post",
)
def admin_revert_last(
    user: UserCtx = Depends(require_admin),
    year: YearInt = Path(...),
    month: MonthInt = Path(...),
    doctor_id: int = Path(..., ge=1),
):
    _guard_period_closed(year, month)
    return revert_last(year=year, month=month, doctor_id=doctor_id, actor=user)


@router.post(
    "/api/v1/preferences/{year}/{month}/{doctor_id}/revert-next",
    response_model=PreferenceRevertRead,
    tags=["preferences:admin"],
    summary="REDO one checkpoint",
    operation_id="preferences_admin_revert_next_post",
)
def admin_revert_next(
    user: UserCtx = Depends(require_admin),
    year: YearInt = Path(...),
    month: MonthInt = Path(...),
    doctor_id: int = Path(..., ge=1),
):
    _guard_period_closed(year, month)
    return revert_next(year=year, month=month, doctor_id=doctor_id, actor=user)
