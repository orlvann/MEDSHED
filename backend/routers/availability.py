# backend/routers/availability.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from backend.models.schemas.availability import (
    AvailabilityDayRead,
    AvailabilityOverviewRead,
)
from backend.routers.deps import UserCtx, require_admin
from backend.services.availability_service import (
    get_day_availability,
    get_month_availability,
)

router = APIRouter(prefix="/api/v1/availability", tags=["availability"])


@router.get(
    "/overview",
    response_model=AvailabilityOverviewRead,
    summary="Monthly availability overview (admin pre-flight coverage)",
    operation_id="availability_overview",
)
def availability_overview(
    year: int = Query(..., ge=1900, le=2100),
    month: int = Query(..., ge=1, le=12),
    user: UserCtx = Depends(require_admin),
):
    """
    Admin-only: show availability per day (counts + risk) before running the solver.

    Uses real doctors + preferences data:
    - only active doctors are counted,
    - missing preferences = fully available (but still visible as 'missing' in summary).
    """
    return get_month_availability(year=year, month=month, actor=user)


@router.get(
    "/{year}/{month}/{day}",
    response_model=AvailabilityDayRead,
    summary="Day drill-down of availability (admin pre-flight coverage)",
    operation_id="availability_day_drilldown",
)
def availability_day_drilldown(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    day: int = Path(..., ge=1, le=31),
    user: UserCtx = Depends(require_admin),
):
    """
    Admin-only: show which doctors are available on a specific day,
    split into duty/on-call and resident/specialist lists.
    """
    data = get_day_availability(year=year, month=month, day=day, actor=user)
    if data is None:
        raise HTTPException(status_code=404, detail="day_out_of_range")
    return data
