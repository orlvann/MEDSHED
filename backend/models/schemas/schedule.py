# backend/models/schemas/schedule.py
# DTOs for schedule generation, working edits, checkpoints, publishing and reading.
# Public API shapes for /api/v1/schedules* (framework-agnostic).

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Dict, List, Literal, Optional

from annotated_types import Ge, Le
from pydantic import BaseModel, Field, field_validator

from .common import (
    DayInt,  # 1..31
    PeriodStatus,  # "past" | "current" | "future"
    ScheduleStatus,  # "draft" | "published"
    ShiftType,  # "on_duty" | "on_call"
    normalize_days,
)

if TYPE_CHECKING:
    from .diagnostics import DiagnosticsRead


# Typed alias for month
MonthInt = Annotated[int, Ge(1), Le(12)]  # 1..12


class Assignment(BaseModel):
    """One assignment cell in the schedule grid."""

    day: DayInt
    shift_type: ShiftType
    doctor_id: int


class SchedulePayload(BaseModel):
    """Versioned snapshot payload (draft/published)."""

    participant_doctor_ids: List[int]
    assignments: List[Assignment]
    # meta.labels must exist; meta.exceptions is optional list of dicts kept as-is
    meta: Dict = Field(default_factory=lambda: {"labels": []})


class ScheduleWorkingRead(BaseModel):
    """GET /api/v1/schedules/{year}/{month}/working (or part of Period View)."""

    year: int
    month: MonthInt
    exists: bool = True
    participant_doctor_ids: List[int] = []
    assignments: List[Assignment] = []
    meta: Dict = Field(default_factory=lambda: {"labels": []})
    updated_at: datetime


class ScheduleWorkingPut(BaseModel):
    """PUT /api/v1/schedules/{year}/{month}/working"""

    assignments: List[Assignment]
    meta: Optional[Dict] = None
    if_unmodified_since: Optional[datetime] = None


class ScheduleDraftView(BaseModel):
    """Draft pointer block presented in Period View / checkpoint responses."""

    version_id: Optional[str] = None
    checkpoints_count: int = 0
    can_undo: bool = False
    can_redo: bool = False
    payload: Optional[SchedulePayload] = None


class SchedulePublishedView(BaseModel):
    """Published pointer block presented in Period View / publish responses."""

    version_id: Optional[str] = None
    publications_count: int = 0
    can_undo: bool = False
    can_redo: bool = False
    payload: Optional[SchedulePayload] = None


class _ViewHint(BaseModel):
    default_mode: Literal["draft", "published"] = "draft"
    toggle_available: bool = True


class SchedulesPeriodViewRead(BaseModel):
    """GET /api/v1/schedules/{year}/{month} (Admin tab – Period View)."""

    year: int
    month: MonthInt
    org_timezone: str = "Europe/Warsaw"
    period_status: PeriodStatus = PeriodStatus.current
    view: _ViewHint = Field(default_factory=_ViewHint)
    # blocks
    working: ScheduleWorkingRead
    draft: ScheduleDraftView
    published: SchedulePublishedView
    diagnostics: "DiagnosticsRead"


# ---- Generate --------------------------------------------------------------


class IgnoreSlot(BaseModel):
    day: DayInt
    shift_type: ShiftType


class ScheduleGenerateRequest(BaseModel):
    """POST /api/v1/schedules/generate"""

    year: int
    month: MonthInt
    participant_doctor_ids: List[int]
    ignore_days: List[DayInt] = []
    ignore_slots: List[IgnoreSlot] = []

    @field_validator("ignore_days", mode="before")
    @classmethod
    def _dedupe_days(cls, v):
        return normalize_days(v)


class ScheduleGenerateCreated(BaseModel):
    """201 response for Generate."""

    year: int
    month: MonthInt
    status: ScheduleStatus = ScheduleStatus.draft
    working: ScheduleWorkingRead
    draft: ScheduleDraftView
    diagnostics: "DiagnosticsRead"


# ---- Draft checkpoint / revert --------------------------------------------


class ScheduleCheckpointRequest(BaseModel):
    """POST /api/v1/schedules/{y}/{m}/checkpoint"""

    note: Optional[str] = None


class ScheduleCheckpointCreated(BaseModel):
    """201 after checkpoint save."""

    year: int
    month: MonthInt
    draft: ScheduleDraftView
    diagnostics: "DiagnosticsRead"


class ScheduleRevertRead(BaseModel):
    """200 after draft UNDO/REDO revert."""

    year: int
    month: MonthInt
    draft: ScheduleDraftView
    working: ScheduleWorkingRead
    diagnostics: "DiagnosticsRead"


# ---- Publish ---------------------------------------------------------------


class AcceptedException(BaseModel):
    code: str
    justification: str


class SchedulePublishRequest(BaseModel):
    """POST /api/v1/schedules/{y}/{m}/publish"""

    force: bool = False
    note: Optional[str] = None
    accepted_exceptions: List[AcceptedException] = []


class SchedulePublishCreated(BaseModel):
    """201 after successful publish."""

    year: int
    month: MonthInt
    published: SchedulePublishedView


class SchedulePublishedRevertRead(BaseModel):
    """200 after published rollback/redo."""

    year: int
    month: MonthInt
    published: SchedulePublishedView


# ---- Doctor path: published + my assignments --------------------------------


class SchedulePublishedRead(BaseModel):
    """GET /api/v1/schedules/{y}/{m}/published (Doctor path)."""

    year: int
    month: MonthInt
    org_timezone: str = "Europe/Warsaw"
    period_status: PeriodStatus = PeriodStatus.current
    published: SchedulePublishedView


class MyAssignment(BaseModel):
    day: DayInt
    shift_type: ShiftType


class MyAssignmentsRead(BaseModel):
    """GET /api/v1/schedules/{y}/{m}/my-assignments"""

    doctor_id: int
    year: int
    month: MonthInt
    assignments: List[MyAssignment] = []
