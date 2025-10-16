# backend/models/schemas/schedule.py
# DTOs for schedule generation, manual edits, publishing and reading.
# These are public API shapes (what /api/v1/schedules* returns/accepts).
# Keep them framework-agnostic and strict.

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from annotated_types import Ge, Le
from pydantic import BaseModel, Field

from .common import ScheduleStatus, ShiftType

# Typed aliases for common bounded ints
MonthInt = Annotated[int, Ge(1), Le(12)]  # 1..12
DayInt = Annotated[int, Ge(1), Le(31)]  # 1..31


class AssignmentRead(BaseModel):
    """One shift assignment for a given day (OnDuty / OnCall)."""

    day: DayInt
    shift_type: ShiftType
    doctor_id: int

    # Service-layer should ensure exactly two assignments per day
    # (one OnDuty and one OnCall) when building a full schedule.


class GenerateScheduleRequest(BaseModel):
    """Input to trigger solver for a given month/department."""

    year: int
    month: MonthInt
    department_id: Optional[str] = Field(
        default=None, description="Optional department key (e.g., 'ER')."
    )
    # Future toggles: time_limit_sec, use_seeding, heuristic_polish, etc.

    model_config = {"json_schema_extra": {"example": {"year": 2026, "month": 2}}}


class ManualEditRequest(BaseModel):
    """Admin-initiated manual change (replace or swap)."""

    day: DayInt
    shift_type: ShiftType
    to_doctor_id: int
    reason: Optional[str] = None
    # For swap auditing (optional: when replacing A->B, set from_doctor_id=A)
    from_doctor_id: Optional[int] = None


class PublishRequest(BaseModel):
    """Optional note when publishing a schedule."""

    note: Optional[str] = None


class ScheduleRead(BaseModel):
    """Full schedule payload returned to UI."""

    id: int
    year: int
    month: MonthInt
    status: ScheduleStatus
    created_by: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    # Optionally include who published and when (fill from service once you track it)
    published_at: Optional[datetime] = None
    published_by: Optional[int] = None

    assignments: list[AssignmentRead] = Field(
        default_factory=list,
        description="Exactly two entries per valid calendar day: OnDuty and OnCall.",
    )

    # You can add lightweight, already-computed stats for UI (optional)
    # stats: Optional[dict] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 42,
                "year": 2026,
                "month": 2,
                "status": "draft",
                "created_by": 1,
                "created_at": "2025-01-20T12:34:56Z",
                "updated_at": None,
                "assignments": [
                    {"day": 1, "shift_type": "OnDuty", "doctor_id": 5},
                    {"day": 1, "shift_type": "OnCall", "doctor_id": 2},
                ],
            }
        }
    }


# ---- Optional helper for history lists (/api/v1/history) ----------------------


class ScheduleHistoryItem(BaseModel):
    """Compact shape used by history listings."""

    schedule_id: int
    year: int
    month: MonthInt
    status: ScheduleStatus
    published_at: Optional[datetime] = None


class ScheduleHistoryList(BaseModel):
    items: list[ScheduleHistoryItem]
    total: int
