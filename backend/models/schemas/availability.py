# backend/models/schemas/availability.py
from __future__ import annotations

from pydantic import BaseModel, Field

from backend.models.common_enums import PeriodStatus, RiskLevel, ShiftType
from backend.models.schemas.doctor import DoctorMini
from backend.models.schemas.dto_common import DayInt, MonthInt, YearInt


class AvailabilityIgnoreSlot(BaseModel):
    """
    One slot that the backend suggests to ignore during Generate,
    so the solver can still produce a draft with intentional gaps.

    - day: calendar day number (1..31)
    - shift_type: "onsite" or "oncall"
    """

    day: DayInt
    shift_type: ShiftType  # "onsite" | "oncall"


class AvailabilityDaySummary(BaseModel):
    """One calendar day for the monthly overview (heatmap)."""

    day: DayInt

    # How many doctors are available by role and category.
    available_specialists_onsite: int
    available_residents_onsite: int
    available_specialists_oncall: int
    available_residents_oncall: int

    # Overall risk flag for this day (ok / critical).
    # FINAL POLICY:
    # - ok: no hard availability problems
    # - critical: missing candidates for any required slot OR no specialist for the day
    risk: RiskLevel

    # Machine-readable issue codes explaining why the day is risky.
    # - ok: usually []
    # - critical: contains blocking codes (e.g. "no_onsite_candidate", "no_specialist")
    risk_issues: list[str] = Field(default_factory=list)

    # Suggested ignores (ONLY for critical days):
    # Backend can compute a minimal set of slots to ignore so Generate can proceed.
    suggested_ignored_slots: list[AvailabilityIgnoreSlot] = Field(default_factory=list)

    # The reason codes that caused the suggestion above (usually a subset of risk_issues).
    suggested_ignore_reason_codes: list[str] = Field(default_factory=list)


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

    # Same meaning as in AvailabilityDaySummary (ok / critical).
    risk: RiskLevel

    # Same meaning as in AvailabilityDaySummary.
    risk_issues: list[str] = Field(default_factory=list)

    # Same suggested ignores (only for critical).
    suggested_ignored_slots: list[AvailabilityIgnoreSlot] = Field(default_factory=list)
    suggested_ignore_reason_codes: list[str] = Field(default_factory=list)


__all__ = [
    "AvailabilityIgnoreSlot",
    "AvailabilityDaySummary",
    "AvailabilityOverviewRead",
    "AvailabilityDayRead",
]
