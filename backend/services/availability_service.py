# backend/models/schemas/availability.py
"""MVP stubs for Admin pre-flight coverage (overview + day drill-down)."""

from __future__ import annotations

from typing import List, Union, cast

from backend.models.common_enums import PeriodStatus  # Literal['past','current','future']
from backend.models.schemas.availability import (
    AvailabilityDayRead,
    AvailabilityDaySummary,
    AvailabilityOverviewRead,
    AvailabilityRiskLevel,
)
from backend.models.schemas.doctor import DoctorMini

# Simple month length map (stub). Replace with a real calendar util later.
_MONTH_LEN = {1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


def _days_in_month(_: int, month: int) -> int:
    """Return month length (stub; Feb=29 to keep it simple)."""
    return _MONTH_LEN.get(month, 30)


def _as_period_status(value: Union[PeriodStatus, str]) -> PeriodStatus:
    """Return a PeriodStatus Literal regardless of input (enum-like str or Literal)."""
    if isinstance(value, str) and value in ("past", "current", "future"):
        return cast(PeriodStatus, value)
    # Fallback to "current" if anything unexpected arrives
    return cast(PeriodStatus, value if value in ("past", "current", "future") else "current")


def compute_overview_stub(
    *, year: int, month: int, org_tz: str, period_status: Union[PeriodStatus, str]
) -> AvailabilityOverviewRead:
    """Deterministic monthly overview for UI (no DB yet)."""
    days = _days_in_month(year, month)
    summaries: List[AvailabilityDaySummary] = []
    for d in range(1, days + 1):
        # Fake availability pattern
        spec = 5 if d % 5 else 0
        res = 6 if d % 3 else 2

        if spec == 0:
            risk = AvailabilityRiskLevel.critical
        elif spec <= 1 or res <= 1:
            risk = AvailabilityRiskLevel.alert
        else:
            risk = AvailabilityRiskLevel.ok

        summaries.append(
            AvailabilityDaySummary(
                day=d,
                available_specialists=spec,
                available_residents=res,
                risk=risk,
            )
        )

    return AvailabilityOverviewRead(
        year=year,
        month=month,
        org_timezone=org_tz,
        period_status=_as_period_status(period_status),
        days=summaries,
    )


def compute_day_drilldown_stub(
    *, year: int, month: int, day: int, org_tz: str, period_status: Union[PeriodStatus, str]
) -> AvailabilityDayRead | None:
    """Deterministic per-day drill-down (no DB yet). Return None if out of range."""
    if day < 1 or day > _days_in_month(year, month):
        return None

    # Fake small pools
    specialists = [
        DoctorMini(id=i, first_name=f"Spec{i}", last_name="Nowak") for i in range(1, 6) if (i + day) % 5 != 0
    ]
    residents = [
        DoctorMini(id=10 + i, first_name=f"Res{i}", last_name="Kowalska") for i in range(1, 6) if (i * day) % 7 != 0
    ]

    risk = (
        AvailabilityRiskLevel.critical
        if len(specialists) == 0
        else (AvailabilityRiskLevel.alert if len(specialists) <= 1 or len(residents) <= 1 else AvailabilityRiskLevel.ok)
    )

    return AvailabilityDayRead(
        year=year,
        month=month,
        day=day,
        org_timezone=org_tz,
        period_status=_as_period_status(period_status),
        specialists=specialists,
        residents=residents,
        risk=risk,
    )
