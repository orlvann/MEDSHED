# backend/routers/availability.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from backend.models.schemas.availability import (
    AvailabilityDayRead,
    AvailabilityOverviewRead,
)
from backend.routers.deps import UserCtx, require_admin
from backend.services.availability_service import (
    compute_day_drilldown_stub,
    compute_overview_stub,
)
from backend.utils import ORG_TZ, get_period_status

# Public router exported by this module (FastAPI picks this up in app.py)
router = APIRouter(prefix="/api/v1/availability", tags=["availability"])


@router.get(
    "/overview",
    response_model=AvailabilityOverviewRead,
    summary="Monthly availability overview (admin pre-flight coverage)",
    operation_id="availability_overview",
    dependencies=[Depends(require_admin)],
)
def availability_overview(
    year: int = Query(..., ge=1900, le=2100),
    month: int = Query(..., ge=1, le=12),
    user: UserCtx = Depends(require_admin),
):
    """Return a deterministic month overview (MVP stub)."""
    period_status = get_period_status(year, month)
    return compute_overview_stub(year=year, month=month, org_tz=ORG_TZ, period_status=period_status)


@router.get(
    "/{year}/{month}/{day}",
    response_model=AvailabilityDayRead,
    summary="Day drill-down of availability (admin pre-flight coverage)",
    operation_id="availability_day_drilldown",
    dependencies=[Depends(require_admin)],
)
def availability_day_drilldown(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    day: int = Path(..., ge=1, le=31),
    user: UserCtx = Depends(require_admin),
):
    """Return per-day drill-down; 404 if day is out of range (MVP stub)."""
    period_status = get_period_status(year, month)
    data = compute_day_drilldown_stub(year=year, month=month, day=day, org_tz=ORG_TZ, period_status=period_status)
    if data is None:
        raise HTTPException(status_code=404, detail="not_found")
    return data
