# backend/services/availability_service.py
"""
Availability Service — admin pre-flight coverage check.

This module computes:
- Monthly availability overview (heatmap) for admin.
- Per-day drill-down (who is available) for admin.

Data sources:
- Doctors ORM (only is_active = True are considered).
- Preferences (via checkpoints in PreferenceVersion + PreferencePointer).

Policy:
- If an active doctor has NO preferences for {year, month}:
  -> treat them as fully available (all days, on-site + on-call).
  -> but they still appear as "missing" in Preferences summary.
"""

from __future__ import annotations

from typing import Dict, List, Set, Tuple

from backend.core.issues import classify_availability_risk_with_reasons
from backend.db.session import SessionLocal
from backend.models.common_enums import DoctorRole, PeriodStatus
from backend.models.orm.doctor import Doctor
from backend.models.orm.preference import PreferencePointer, PreferenceVersion
from backend.models.schemas.availability import (
    AvailabilityDayRead,
    AvailabilityDaySummary,
    AvailabilityOverviewRead,
)
from backend.models.schemas.doctor import DoctorMini
from backend.services.preference_service import ensure_latest_checkpoints_for_period
from backend.utils.timez import ORG_TZ, days_in_month, get_period_status


def _compute_available_days_for_doctor(
    session,
    *,
    year: int,
    month: int,
    doctor_id: int,
) -> Tuple[Set[int], Set[int]]:
    """
    For a given doctor and period, return days where they are available.

    Returns:
        (available_onsite_days, available_oncall_days) as sets of day numbers.

    Rules:
    - If there is NO checkpoint for this doctor+period:
        -> treat doctor as fully available (all days, both categories).
    - If there is a checkpoint:
        -> read payload from PreferenceVersion and use "unavailable_*" lists
           to mark days as unavailable; all other days are available.
    """
    num_days = days_in_month(year, month)
    all_days = set(range(1, num_days + 1))

    # Load pointer for this doctor+period.
    pointer: PreferencePointer | None = (
        session.query(PreferencePointer).filter_by(year=year, month=month, doctor_id=doctor_id).one_or_none()
    )

    # No pointer or no current version -> no preferences; fully available.
    if pointer is None or pointer.current_version_id is None:
        return all_days, all_days

    # Load the checkpoint payload (immutable snapshot).
    version: PreferenceVersion | None = (
        session.query(PreferenceVersion).filter_by(id=pointer.current_version_id).one_or_none()
    )
    if version is None or version.payload is None:
        # Defensive: if something is wrong, fallback to fully available.
        return all_days, all_days

    payload = version.payload

    unavailable_onsite = set(payload.get("unavailable_onsite_days") or [])
    unavailable_oncall = set(payload.get("unavailable_oncall_days") or [])

    # Preferred lists are not used here – availability is defined by "unavailable_*".
    available_onsite = {d for d in all_days if d not in unavailable_onsite}
    available_oncall = {d for d in all_days if d not in unavailable_oncall}

    return available_onsite, available_oncall


# NOTE:
# Risk classification is shared in backend/core/risk.py now (single source of truth).
# Use classify_day_risk_for_availability(...) instead of a local helper.


def get_month_availability(*, year: int, month: int, actor) -> AvailabilityOverviewRead:
    """
    Compute monthly availability overview for admin.

    Steps:
    1) Ensure latest checkpoints reflect newest working snapshots.
    2) Load all active doctors.
    3) For each doctor, compute available days for onsite/on-call.
    4) Aggregate counts per day and compute RiskLevel.
    """
    # Step 1: sync working → checkpoints where needed.
    ensure_latest_checkpoints_for_period(year=year, month=month)

    period_status = PeriodStatus(get_period_status(year, month))
    org_tz = ORG_TZ
    num_days = days_in_month(year, month)

    # Pre-initialize counters for each day.
    spec_onsite_counts: Dict[int, int] = {d: 0 for d in range(1, num_days + 1)}
    res_onsite_counts: Dict[int, int] = {d: 0 for d in range(1, num_days + 1)}
    spec_oncall_counts: Dict[int, int] = {d: 0 for d in range(1, num_days + 1)}
    res_oncall_counts: Dict[int, int] = {d: 0 for d in range(1, num_days + 1)}

    with SessionLocal() as session:
        # Step 2: get all active doctors.
        doctors: List[Doctor] = session.query(Doctor).filter_by(is_active=True).all()

        # Step 3: for each doctor, compute availability and update daily counters.
        for doc in doctors:
            available_onsite, available_oncall = _compute_available_days_for_doctor(
                session, year=year, month=month, doctor_id=doc.id
            )

            for day in range(1, num_days + 1):
                if day in available_onsite:
                    if doc.role == DoctorRole.specialist:
                        spec_onsite_counts[day] += 1
                    else:
                        res_onsite_counts[day] += 1

                if day in available_oncall:
                    if doc.role == DoctorRole.specialist:
                        spec_oncall_counts[day] += 1
                    else:
                        res_oncall_counts[day] += 1

        # Step 4: build summaries with risk and issues for each day.
        day_summaries: List[AvailabilityDaySummary] = []
        for day in range(1, num_days + 1):
            spec_onsite = spec_onsite_counts[day]
            res_onsite = res_onsite_counts[day]
            spec_oncall = spec_oncall_counts[day]
            res_oncall = res_oncall_counts[day]

            # Use shared helper to compute risk and issues
            details = classify_availability_risk_with_reasons(
                spec_onsite=spec_onsite,
                res_onsite=res_onsite,
                spec_oncall=spec_oncall,
                res_oncall=res_oncall,
            )

            day_summaries.append(
                AvailabilityDaySummary(
                    day=day,
                    available_specialists_onsite=spec_onsite,
                    available_residents_onsite=res_onsite,
                    available_specialists_oncall=spec_oncall,
                    available_residents_oncall=res_oncall,
                    risk=details.risk,
                    risk_issues=details.issues,
                )
            )

    return AvailabilityOverviewRead(
        year=year,
        month=month,
        org_timezone=org_tz,
        period_status=period_status,
        days=day_summaries,
    )


def get_day_availability(*, year: int, month: int, day: int, actor) -> AvailabilityDayRead | None:
    """
    Compute per-day drill-down (which doctors are available on that day).

    Returns:
        AvailabilityDayRead  -> if day is valid for this month.
        None                 -> if day is out of range (caller should return 404).
    """
    num_days = days_in_month(year, month)
    if day < 1 or day > num_days:
        return None

    # Ensure checkpoints are up-to-date before reading preferences.
    ensure_latest_checkpoints_for_period(year=year, month=month)

    period_status = PeriodStatus(get_period_status(year, month))
    org_tz = ORG_TZ

    specialists_onsite: List[DoctorMini] = []
    residents_onsite: List[DoctorMini] = []
    specialists_oncall: List[DoctorMini] = []
    residents_oncall: List[DoctorMini] = []

    with SessionLocal() as session:
        doctors: List[Doctor] = session.query(Doctor).filter_by(is_active=True).all()

        for doc in doctors:
            available_onsite, available_oncall = _compute_available_days_for_doctor(
                session, year=year, month=month, doctor_id=doc.id
            )

            mini = DoctorMini(id=doc.id, first_name=doc.first_name, last_name=doc.last_name)

            if day in available_onsite:
                if doc.role == DoctorRole.specialist:
                    specialists_onsite.append(mini)
                else:
                    residents_onsite.append(mini)

            if day in available_oncall:
                if doc.role == DoctorRole.specialist:
                    specialists_oncall.append(mini)
                else:
                    residents_oncall.append(mini)

        # Compute risk and issues based on counts for this single day.
        details = classify_availability_risk_with_reasons(
            spec_onsite=len(specialists_onsite),
            res_onsite=len(residents_onsite),
            spec_oncall=len(specialists_oncall),
            res_oncall=len(residents_oncall),
        )

    return AvailabilityDayRead(
        year=year,
        month=month,
        day=day,
        org_timezone=org_tz,
        period_status=period_status,
        specialists_onsite=specialists_onsite,
        residents_onsite=residents_onsite,
        specialists_oncall=specialists_oncall,
        residents_oncall=residents_oncall,
        risk=details.risk,
        risk_issues=details.issues,
    )
