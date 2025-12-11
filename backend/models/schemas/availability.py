# backend/models/schemas/availability.py
from __future__ import annotations

from pydantic import BaseModel, Field

from backend.models.common_enums import PeriodStatus, RiskLevel
from backend.models.schemas.doctor import DoctorMini
from backend.models.schemas.dto_common import DayInt, MonthInt, YearInt


class AvailabilityDaySummary(BaseModel):
    """One calendar day for the monthly overview (heatmap)."""

    day: DayInt

    # How many doctors are available by role and category.
    available_specialists_onsite: int
    available_residents_onsite: int
    available_specialists_oncall: int
    available_residents_oncall: int

    # Overall risk flag for this day (ok / alert / critical).
    risk: RiskLevel


class AvailabilityOverviewRead(BaseModel):
    """Monthly overview (input for the 'Generate New Draft' calendar)."""

    year: YearInt
    month: MonthInt
    org_timezone: str
    period_status: PeriodStatus  # 'past' | 'current' | 'future'

    # One entry per calendar day with counts and risk level.
    days: list[AvailabilityDaySummary] = Field(default_factory=list)


class AvailabilityDayRead(BaseModel):
    """Drill-down view for a single day (who is available)."""

    year: YearInt
    month: MonthInt
    day: DayInt
    org_timezone: str
    period_status: PeriodStatus

    # Doctors available that day for each category and role.
    specialists_onsite: list[DoctorMini] = Field(default_factory=list)
    residents_onsite: list[DoctorMini] = Field(default_factory=list)
    specialists_oncall: list[DoctorMini] = Field(default_factory=list)
    residents_oncall: list[DoctorMini] = Field(default_factory=list)

    risk: RiskLevel


__all__ = [
    "AvailabilityDaySummary",
    "AvailabilityOverviewRead",
    "AvailabilityDayRead",
]
