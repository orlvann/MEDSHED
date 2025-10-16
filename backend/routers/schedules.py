# backend/routers/schedules.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Path, Query, status

from backend.models.schemas import (
    # schedule shapes
    AssignmentRead,
    GenerateScheduleRequest,
    ManualEditRequest,
    PublishRequest,
    # history shapes
    ScheduleHistoryItem,
    ScheduleHistoryList,
    ScheduleRead,
    ScheduleStatus,
)

router = APIRouter(tags=["schedules"])

# ---- Generate ---------------------------------------------------------------


@router.post(
    "/api/v1/schedules/generate",
    response_model=ScheduleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Run solver and create schedule",
)
def generate(payload: GenerateScheduleRequest = Body(...)):
    # TODO: scheduling_service.generate(payload)
    return {
        "id": 42,
        "year": payload.year,
        "month": payload.month,
        "status": ScheduleStatus.DRAFT,
        "created_by": 1,
        "created_at": datetime.now(timezone.utc),
        "updated_at": None,
        "assignments": [
            {"day": 1, "shift_type": "OnDuty", "doctor_id": 1},
            {"day": 1, "shift_type": "OnCall", "doctor_id": 3},
        ],
    }


# ---- Read one ---------------------------------------------------------------


@router.get(
    "/api/v1/schedules/{sid}",
    response_model=ScheduleRead,
    summary="Get schedule by id",
)
def get_schedule(sid: int = Path(..., ge=1)):
    # TODO: scheduling_service.get(sid)
    return {
        "id": sid,
        "year": 2026,
        "month": 2,
        "status": ScheduleStatus.DRAFT,
        "created_by": 1,
        "created_at": datetime.now(timezone.utc),
        "updated_at": None,
        "assignments": [],
    }


# ---- Manual edits -----------------------------------------------------------


@router.patch(
    "/api/v1/schedules/{sid}",
    response_model=ScheduleRead,
    summary="Manual edits with validation",
)
def patch_schedule(
    sid: int = Path(..., ge=1),
    payload: list[ManualEditRequest] = Body(...),
):
    # TODO: scheduling_service.apply_manual_edits(sid, payload)
    edits = [
        AssignmentRead(day=e.day, shift_type=e.shift_type, doctor_id=e.to_doctor_id).model_dump()
        for e in payload
    ]
    return {
        "id": sid,
        "year": 2026,
        "month": 2,
        "status": ScheduleStatus.DRAFT,
        "created_by": 1,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "assignments": edits,
    }


# ---- Publish ----------------------------------------------------------------


@router.post(
    "/api/v1/schedules/{sid}/publish",
    summary="Publish schedule",
)
def publish_schedule(
    sid: int = Path(..., ge=1),
    payload: Optional[PublishRequest] = Body(None),
):
    # TODO: scheduling_service.publish(sid, note=payload.note if payload else None)
    return {"status": "published", "publishedAt": datetime.now(timezone.utc).isoformat()}


# ---- Exports (binary) -------------------------------------------------------


@router.get("/api/v1/schedules/{sid}/export.xlsx", summary="Export schedule as XLSX")
def export_xlsx(sid: int = Path(..., ge=1)):
    # TODO: export_service.xlsx(sid) -> StreamingResponse
    return {"detail": "stub: stream XLSX here"}


# ---- History (compact list) -------------------------------------------------


@router.get(
    "/api/v1/history",
    response_model=ScheduleHistoryList,
    summary="Browse past schedules (compact list)",
)
def list_history(
    from_year: int = Query(..., ge=1900, le=2100),
    from_month: int = Query(..., ge=1, le=12),
    to_year: int = Query(..., ge=1900, le=2100),
    to_month: int = Query(..., ge=1, le=12),
):
    """
    Stub implementation for FE integration. Replace with DB query.
    """
    item = ScheduleHistoryItem(
        schedule_id=41,
        year=2026,
        month=1,
        status=ScheduleStatus.PUBLISHED,
        published_at=datetime(2026, 1, 28, tzinfo=timezone.utc),
    )
    return {
        "items": [item.model_dump()],
        "from_year": from_year,
        "from_month": from_month,
        "to_year": to_year,
        "to_month": to_month,
        "total": 1,
    }
