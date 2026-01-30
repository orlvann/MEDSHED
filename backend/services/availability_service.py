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

from backend.core.issues import (
    FORCED_DOUBLE_SHIFT_SAME_DAY,
    NO_ONCALL_CANDIDATE,
    NO_ONSITE_CANDIDATE,
    NO_SPECIALIST,
    classify_availability_risk_with_reasons,
    is_forced_double_shift_same_day,
)
from backend.db.session import SessionLocal
from backend.models.common_enums import DoctorRole, PeriodStatus, RiskLevel, ShiftType
from backend.models.orm.doctor import Doctor
from backend.models.orm.preference import PreferencePointer, PreferenceVersion
from backend.models.schemas import (
    AvailabilityDayRead,
    AvailabilityDaySummary,
    AvailabilityIgnoreSlot,
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

    pointer: PreferencePointer | None = (
        session.query(PreferencePointer)
        .filter_by(year=int(year), month=int(month), doctor_id=int(doctor_id))
        .one_or_none()
    )

    if pointer is None or pointer.current_version_id is None:
        return all_days, all_days

    version: PreferenceVersion | None = (
        session.query(PreferenceVersion).filter_by(id=int(pointer.current_version_id)).one_or_none()
    )
    if version is None or version.payload is None:
        return all_days, all_days

    payload = version.payload or {}

    unavailable_onsite = set(payload.get("unavailable_onsite_days") or [])
    unavailable_oncall = set(payload.get("unavailable_oncall_days") or [])

    available_onsite = {d for d in all_days if int(d) not in unavailable_onsite}
    available_oncall = {d for d in all_days if int(d) not in unavailable_oncall}

    return available_onsite, available_oncall


def _suggest_ignored_slots_and_reasons(*, risk_issues: List[str]) -> tuple[List[AvailabilityIgnoreSlot], List[str]]:
    """
    Suggest a minimal set of ignore slots so Generate can proceed.

    Deterministic policy:
    1) If a REQUIRED slot has zero candidates -> suggest ignoring that slot.
    2) If the only remaining blocker is NO_SPECIALIST (and we are not already ignoring anything),
       suggest ignoring ONCALL (keep onsite more important).

    IMPORTANT:
    - AvailabilityIgnoreSlot.day is a DayInt (>= 1), so this helper must always build valid objects.
    - We use a placeholder day=1 here. Callers patch it to the real day number.
    """
    suggested: List[AvailabilityIgnoreSlot] = []
    reasons: List[str] = []

    issue_set = set(risk_issues or [])

    # Placeholder that satisfies DayInt validation.
    placeholder_day = 1

    if NO_ONSITE_CANDIDATE in issue_set:
        suggested.append(AvailabilityIgnoreSlot(day=placeholder_day, shift_type=ShiftType.onsite))
        reasons.append(NO_ONSITE_CANDIDATE)

    if NO_ONCALL_CANDIDATE in issue_set:
        suggested.append(AvailabilityIgnoreSlot(day=placeholder_day, shift_type=ShiftType.oncall))
        reasons.append(NO_ONCALL_CANDIDATE)

    # If we already ignore something, NO_SPECIALIST stops being a blocker
    # because the specialist rule is required ONLY when BOTH shifts are required.
    if not suggested and (NO_SPECIALIST in issue_set):
        suggested.append(AvailabilityIgnoreSlot(day=placeholder_day, shift_type=ShiftType.oncall))
        reasons.append(NO_SPECIALIST)

    return suggested, reasons


def get_month_availability(*, year: int, month: int, actor) -> AvailabilityOverviewRead:
    """
    Compute monthly availability overview for admin.

    FINAL POLICY:
    - This is "business-required" mode: every day requires onsite + oncall.
    - ignore_slots/ignore_days do not exist here.
    """
    ensure_latest_checkpoints_for_period(year=year, month=month)

    period_status = PeriodStatus(get_period_status(year, month))
    org_tz = ORG_TZ
    num_days = days_in_month(year, month)

    spec_onsite_counts: Dict[int, int] = {d: 0 for d in range(1, num_days + 1)}
    res_onsite_counts: Dict[int, int] = {d: 0 for d in range(1, num_days + 1)}
    spec_oncall_counts: Dict[int, int] = {d: 0 for d in range(1, num_days + 1)}
    res_oncall_counts: Dict[int, int] = {d: 0 for d in range(1, num_days + 1)}

    onsite_ids_by_day: Dict[int, Set[int]] = {d: set() for d in range(1, num_days + 1)}
    oncall_ids_by_day: Dict[int, Set[int]] = {d: set() for d in range(1, num_days + 1)}

    doctor_role_by_id: Dict[int, DoctorRole] = {}

    with SessionLocal() as session:
        doctors: List[Doctor] = session.query(Doctor).filter_by(is_active=True).all()

        for doc in doctors:
            doctor_role_by_id[int(doc.id)] = doc.role

        for doc in doctors:
            available_onsite, available_oncall = _compute_available_days_for_doctor(
                session, year=int(year), month=int(month), doctor_id=int(doc.id)
            )

            for d in range(1, num_days + 1):
                if int(d) in available_onsite:
                    onsite_ids_by_day[d].add(int(doc.id))
                    if doc.role == DoctorRole.specialist:
                        spec_onsite_counts[d] += 1
                    else:
                        res_onsite_counts[d] += 1

                if int(d) in available_oncall:
                    oncall_ids_by_day[d].add(int(doc.id))
                    if doc.role == DoctorRole.specialist:
                        spec_oncall_counts[d] += 1
                    else:
                        res_oncall_counts[d] += 1

        day_summaries: List[AvailabilityDaySummary] = []
        for d in range(1, num_days + 1):
            details = classify_availability_risk_with_reasons(
                onsite_ids=onsite_ids_by_day[d],
                oncall_ids=oncall_ids_by_day[d],
                doctor_role_by_id=doctor_role_by_id,
                onsite_required=True,
                oncall_required=True,
            )

            if is_forced_double_shift_same_day(
                onsite_ids=onsite_ids_by_day[d],
                oncall_ids=oncall_ids_by_day[d],
                onsite_required=True,
                oncall_required=True,
            ):
                if FORCED_DOUBLE_SHIFT_SAME_DAY not in details.issues:
                    details.issues.append(FORCED_DOUBLE_SHIFT_SAME_DAY)

            suggested_ignored_slots: List[AvailabilityIgnoreSlot] = []
            suggested_ignore_reason_codes: List[str] = []

            if details.risk == RiskLevel.critical:
                raw_suggested, raw_reasons = _suggest_ignored_slots_and_reasons(risk_issues=details.issues)

                # Patch placeholder day -> real day number.
                suggested_ignored_slots = [
                    AvailabilityIgnoreSlot(day=int(d), shift_type=s.shift_type) for s in (raw_suggested or [])
                ]
                suggested_ignore_reason_codes = list(raw_reasons or [])

            day_summaries.append(
                AvailabilityDaySummary(
                    day=int(d),
                    available_specialists_onsite=int(spec_onsite_counts[d]),
                    available_residents_onsite=int(res_onsite_counts[d]),
                    available_specialists_oncall=int(spec_oncall_counts[d]),
                    available_residents_oncall=int(res_oncall_counts[d]),
                    risk=details.risk,
                    risk_issues=list(details.issues or []),
                    suggested_ignored_slots=suggested_ignored_slots,
                    suggested_ignore_reason_codes=suggested_ignore_reason_codes,
                )
            )

    return AvailabilityOverviewRead(
        year=int(year),
        month=int(month),
        org_timezone=str(org_tz),
        period_status=period_status,
        days=day_summaries,
    )


def get_day_availability(*, year: int, month: int, day: int, actor) -> AvailabilityDayRead | None:
    """
    Compute per-day drill-down (which doctors are available on that day).

    FINAL POLICY:
    - This is "business-required" mode: the day requires onsite + oncall.
    - ignore_slots/ignore_days do not exist here.
    """
    num_days = days_in_month(year, month)
    if int(day) < 1 or int(day) > int(num_days):
        return None

    ensure_latest_checkpoints_for_period(year=year, month=month)

    period_status = PeriodStatus(get_period_status(year, month))
    org_tz = ORG_TZ

    specialists_onsite: List[DoctorMini] = []
    residents_onsite: List[DoctorMini] = []
    specialists_oncall: List[DoctorMini] = []
    residents_oncall: List[DoctorMini] = []

    onsite_ids: Set[int] = set()
    oncall_ids: Set[int] = set()

    doctor_role_by_id: Dict[int, DoctorRole] = {}

    with SessionLocal() as session:
        doctors: List[Doctor] = session.query(Doctor).filter_by(is_active=True).all()

        for doc in doctors:
            doctor_role_by_id[int(doc.id)] = doc.role

        for doc in doctors:
            available_onsite, available_oncall = _compute_available_days_for_doctor(
                session, year=int(year), month=int(month), doctor_id=int(doc.id)
            )

            mini = DoctorMini(id=int(doc.id), first_name=doc.first_name, last_name=doc.last_name)

            if int(day) in available_onsite:
                onsite_ids.add(int(doc.id))
                if doc.role == DoctorRole.specialist:
                    specialists_onsite.append(mini)
                else:
                    residents_onsite.append(mini)

            if int(day) in available_oncall:
                oncall_ids.add(int(doc.id))
                if doc.role == DoctorRole.specialist:
                    specialists_oncall.append(mini)
                else:
                    residents_oncall.append(mini)

        details = classify_availability_risk_with_reasons(
            onsite_ids=onsite_ids,
            oncall_ids=oncall_ids,
            doctor_role_by_id=doctor_role_by_id,
            onsite_required=True,
            oncall_required=True,
        )

        if is_forced_double_shift_same_day(
            onsite_ids=onsite_ids,
            oncall_ids=oncall_ids,
            onsite_required=True,
            oncall_required=True,
        ):
            if FORCED_DOUBLE_SHIFT_SAME_DAY not in details.issues:
                details.issues.append(FORCED_DOUBLE_SHIFT_SAME_DAY)

    suggested_ignored_slots: List[AvailabilityIgnoreSlot] = []
    suggested_ignore_reason_codes: List[str] = []

    if details.risk == RiskLevel.critical:
        raw_suggested, raw_reasons = _suggest_ignored_slots_and_reasons(risk_issues=details.issues)

        # Patch placeholder day -> real day number.
        suggested_ignored_slots = [
            AvailabilityIgnoreSlot(day=int(day), shift_type=s.shift_type) for s in (raw_suggested or [])
        ]
        suggested_ignore_reason_codes = list(raw_reasons or [])

    specialists_onsite.sort(key=lambda x: int(x.id))
    residents_onsite.sort(key=lambda x: int(x.id))
    specialists_oncall.sort(key=lambda x: int(x.id))
    residents_oncall.sort(key=lambda x: int(x.id))

    return AvailabilityDayRead(
        year=int(year),
        month=int(month),
        day=int(day),
        org_timezone=str(org_tz),
        period_status=period_status,
        specialists_onsite=specialists_onsite,
        residents_onsite=residents_onsite,
        specialists_oncall=specialists_oncall,
        residents_oncall=residents_oncall,
        risk=details.risk,
        risk_issues=list(details.issues or []),
        suggested_ignored_slots=suggested_ignored_slots,
        suggested_ignore_reason_codes=suggested_ignore_reason_codes,
    )
