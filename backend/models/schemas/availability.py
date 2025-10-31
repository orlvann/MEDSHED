# backend/models/schemas/availability.py
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from backend.models.common_enums import PeriodStatus  # Literal['past','current','future']
from backend.models.schemas.doctor import DoctorMini
from backend.models.schemas.dto_common import DayInt, MonthInt, YearInt


class AvailabilityRiskLevel(str, Enum):
    """Risk level for pre-flight coverage overview."""

    ok = "ok"
    alert = "alert"
    critical = "critical"


class AvailabilityDaySummary(BaseModel):
    """One-day row for the monthly overview."""

    day: DayInt
    available_specialists: int
    available_residents: int
    risk: AvailabilityRiskLevel


class AvailabilityOverviewRead(BaseModel):
    """Monthly overview (heatmap input)."""

    year: YearInt
    month: MonthInt
    org_timezone: str
    period_status: PeriodStatus  # Literal['past','current','future']
    days: list[AvailabilityDaySummary] = Field(default_factory=list)


class AvailabilityDayRead(BaseModel):
    """Drill-down for a single day."""

    year: YearInt
    month: MonthInt
    day: DayInt
    org_timezone: str
    period_status: PeriodStatus  # Literal['past','current','future']
    specialists: list[DoctorMini] = Field(default_factory=list)
    residents: list[DoctorMini] = Field(default_factory=list)
    risk: AvailabilityRiskLevel


__all__ = [
    "AvailabilityRiskLevel",
    "AvailabilityDaySummary",
    "AvailabilityOverviewRead",
    "AvailabilityDayRead",
]
