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
  -> treat them as fully available (all days, duty + on-call).
  -> but they still appear as "missing" in Preferences summary.
"""

from __future__ import annotations

from calendar import monthrange
from typing import Dict, List, Set, Tuple

from backend.db.session import SessionLocal
from backend.models.common_enums import DoctorRole, PeriodStatus, RiskLevel
from backend.models.orm.doctor import Doctor
from backend.models.orm.preference import PreferencePointer, PreferenceVersion
from backend.models.schemas.availability import (
    AvailabilityDayRead,
    AvailabilityDaySummary,
    AvailabilityOverviewRead,
)
from backend.models.schemas.doctor import DoctorMini
from backend.services.preference_service import ensure_latest_checkpoints_for_period
from backend.utils.timez import ORG_TZ, get_period_status

# Tunable thresholds for risk classification.
# You can adjust these later after testing on real data.
MIN_OK_DOCTORS_PER_CATEGORY = 2  # how many doctors per category is considered "safe"
MIN_OK_SPECIALISTS_TOTAL = 2  # how many specialists per day is considered "safe enough"


def _days_in_month(year: int, month: int) -> int:
    """Return the real number of days in given month/year."""
    # monthrange returns (weekday_of_first_day, number_of_days)
    _, days = monthrange(year, month)
    return days


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
        (available_duty_days, available_oncall_days) as sets of day numbers.

    Rules:
    - If there is NO checkpoint for this doctor+period:
        -> treat doctor as fully available (all days, both categories).
    - If there is a checkpoint:
        -> read payload from PreferenceVersion and use "unavailable_*" lists
           to mark days as unavailable; all other days are available.
    """
    days_in_month = _days_in_month(year, month)
    all_days = set(range(1, days_in_month + 1))

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

    unavailable_duty = set(payload.get("unavailable_duty_days") or [])
    unavailable_oncall = set(payload.get("unavailable_oncall_days") or [])

    # Preferred lists are not used here – availability is defined by "unavailable_*".
    available_duty = {d for d in all_days if d not in unavailable_duty}
    available_oncall = {d for d in all_days if d not in unavailable_oncall}

    return available_duty, available_oncall


def _compute_risk_for_day(
    *,
    spec_duty: int,
    res_duty: int,
    spec_oncall: int,
    res_oncall: int,
) -> RiskLevel:
    """
    Compute RiskLevel for a single day based on per-category counts.

    Meaning of inputs:
    - spec_duty / res_duty:     how many specialists / residents are available for ON_DUTY.
    - spec_oncall / res_oncall: how many specialists / residents are available for ON_CALL.

    Derived totals:
    - total_specialists = all specialists available that day (duty + on_call).
    - total_doctors     = all doctors available that day (specialists + residents).
    - total_duty        = all doctors available for ON_DUTY.
    - total_oncall      = all doctors available for ON_CALL.

    Rules:
    - critical:
        * there are 0 or 1 doctors in total (almost nobody to choose from), OR
        * there is no specialist at all (only residents).
    - ok:
        * there are enough doctors in BOTH categories:
          - total_duty   >= MIN_OK_DOCTORS_PER_CATEGORY
          - total_oncall >= MIN_OK_DOCTORS_PER_CATEGORY
        * and there are enough specialists in total:
          - total_specialists >= MIN_OK_SPECIALISTS_TOTAL
    - alert:
        * everything else (not critical and not ok).
    """
    total_specialists = spec_duty + spec_oncall
    total_residents = res_duty + res_oncall
    total_doctors = total_specialists + total_residents

    # Critical if almost nobody is available (0 or 1 doctor total).
    if total_doctors <= 1:
        return RiskLevel.critical

    # Critical if there is no specialist at all (only residents).
    if total_specialists == 0:
        return RiskLevel.critical

    total_duty = spec_duty + res_duty
    total_oncall = spec_oncall + res_oncall

    # "Ok" if both categories have "enough" doctors and specialists.
    if (
        total_duty >= MIN_OK_DOCTORS_PER_CATEGORY
        and total_oncall >= MIN_OK_DOCTORS_PER_CATEGORY
        and total_specialists >= MIN_OK_SPECIALISTS_TOTAL
    ):
        return RiskLevel.ok

    # All other cases are "alert" (feasible but risky).
    return RiskLevel.alert


def get_month_availability(*, year: int, month: int, actor) -> AvailabilityOverviewRead:
    """
    Compute monthly availability overview for admin.

    Steps:
    1) Ensure latest checkpoints reflect newest working snapshots.
    2) Load all active doctors.
    3) For each doctor, compute available days for duty/on-call.
    4) Aggregate counts per day and compute RiskLevel.
    """
    # Step 1: sync working → checkpoints where needed.
    ensure_latest_checkpoints_for_period(year=year, month=month)

    period_status = PeriodStatus(get_period_status(year, month))
    org_tz = ORG_TZ
    days_in_month = _days_in_month(year, month)

    # Pre-initialize counters for each day.
    spec_duty_counts: Dict[int, int] = {d: 0 for d in range(1, days_in_month + 1)}
    res_duty_counts: Dict[int, int] = {d: 0 for d in range(1, days_in_month + 1)}
    spec_oncall_counts: Dict[int, int] = {d: 0 for d in range(1, days_in_month + 1)}
    res_oncall_counts: Dict[int, int] = {d: 0 for d in range(1, days_in_month + 1)}

    with SessionLocal() as session:
        # Step 2: get all active doctors.
        doctors: List[Doctor] = session.query(Doctor).filter_by(is_active=True).all()

        # Step 3: for each doctor, compute availability and update daily counters.
        for doc in doctors:
            available_duty, available_oncall = _compute_available_days_for_doctor(
                session, year=year, month=month, doctor_id=doc.id
            )

            for day in range(1, days_in_month + 1):
                if day in available_duty:
                    if doc.role == DoctorRole.specialist:
                        spec_duty_counts[day] += 1
                    else:
                        res_duty_counts[day] += 1

                if day in available_oncall:
                    if doc.role == DoctorRole.specialist:
                        spec_oncall_counts[day] += 1
                    else:
                        res_oncall_counts[day] += 1

        # Step 4: build summaries with risk for each day.
        day_summaries: List[AvailabilityDaySummary] = []
        for day in range(1, days_in_month + 1):
            spec_duty = spec_duty_counts[day]
            res_duty = res_duty_counts[day]
            spec_oncall = spec_oncall_counts[day]
            res_oncall = res_oncall_counts[day]

            risk = _compute_risk_for_day(
                spec_duty=spec_duty,
                res_duty=res_duty,
                spec_oncall=spec_oncall,
                res_oncall=res_oncall,
            )

            day_summaries.append(
                AvailabilityDaySummary(
                    day=day,
                    available_specialists_duty=spec_duty,
                    available_residents_duty=res_duty,
                    available_specialists_oncall=spec_oncall,
                    available_residents_oncall=res_oncall,
                    risk=risk,
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
    days_in_month = _days_in_month(year, month)
    if day < 1 or day > days_in_month:
        return None

    # Ensure checkpoints are up-to-date before reading preferences.
    ensure_latest_checkpoints_for_period(year=year, month=month)

    period_status = PeriodStatus(get_period_status(year, month))
    org_tz = ORG_TZ

    specialists_duty: List[DoctorMini] = []
    residents_duty: List[DoctorMini] = []
    specialists_oncall: List[DoctorMini] = []
    residents_oncall: List[DoctorMini] = []

    with SessionLocal() as session:
        doctors: List[Doctor] = session.query(Doctor).filter_by(is_active=True).all()

        for doc in doctors:
            available_duty, available_oncall = _compute_available_days_for_doctor(
                session, year=year, month=month, doctor_id=doc.id
            )

            mini = DoctorMini(id=doc.id, first_name=doc.first_name, last_name=doc.last_name)

            if day in available_duty:
                if doc.role == DoctorRole.specialist:
                    specialists_duty.append(mini)
                else:
                    residents_duty.append(mini)

            if day in available_oncall:
                if doc.role == DoctorRole.specialist:
                    specialists_oncall.append(mini)
                else:
                    residents_oncall.append(mini)

    # Compute risk based on counts for this single day.
    risk = _compute_risk_for_day(
        spec_duty=len(specialists_duty),
        res_duty=len(residents_duty),
        spec_oncall=len(specialists_oncall),
        res_oncall=len(residents_oncall),
    )

    return AvailabilityDayRead(
        year=year,
        month=month,
        day=day,
        org_timezone=org_tz,
        period_status=period_status,
        specialists_duty=specialists_duty,
        residents_duty=residents_duty,
        specialists_oncall=specialists_oncall,
        residents_oncall=residents_oncall,
        risk=risk,
    )
