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

from backend.core.feasibility import FeasibilityIssue, compute_day_capacity
from backend.core.issues import (
    FORCED_DOUBLE_SHIFT_SAME_DAY,
    NO_ONCALL_CANDIDATE,
    NO_ONSITE_CANDIDATE,
    NO_SPECIALIST,
    classify_availability_risk_with_reasons,
    is_forced_double_shift_same_day,
)
from backend.core.types import ProblemData
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


def _suggest_ignored_slots_and_reasons(
    *,
    problem: ProblemData,
    precheck_issues: List[FeasibilityIssue],
) -> tuple[List[AvailabilityIgnoreSlot], List[str]]:
    """
    Suggest a minimal set of ignore slots so Generate can proceed.

    Deterministic policy (per-day):
    1) If a slot has zero candidates -> suggest ignoring that slot.
    2) If the only remaining blocker for the day is NO_SPECIALIST:
       - Keep the slot where MORE available candidates marked "preferred".
         Ignore the other slot.
       - If preferred is tied (including both 0), keep the slot with MORE candidates total.
       - If still tied (or both empty), ignore ONCALL (fixed fallback).
    """
    # Build capacity once: day -> candidate ids for each slot.
    capacity_by_day = compute_day_capacity(problem)

    # Group issue codes by day.
    codes_by_day: Dict[int, Set[str]] = {}
    for it in precheck_issues or []:
        codes_by_day.setdefault(int(it.day), set()).add(str(it.code))

    suggested: List[AvailabilityIgnoreSlot] = []
    reasons: Set[str] = set()

    def _count_preferred(day: int, shift_type: ShiftType, candidate_ids: Set[int]) -> int:
        """
        Count how many AVAILABLE candidates marked this slot as preferred.
        Uses PreferencesInput:
          - preferred_onsite_days
          - preferred_oncall_days
        """
        cnt = 0
        for did in candidate_ids:
            pref = problem.preferences.get(int(did))
            if pref is None:
                continue
            preferred_days = (
                pref.preferred_onsite_days if shift_type == ShiftType.onsite else pref.preferred_oncall_days
            )
            if int(day) in preferred_days:
                cnt += 1
        return cnt

    for day in sorted(codes_by_day.keys()):
        code_set = codes_by_day[day]

        cap = capacity_by_day.get(int(day))
        onsite_ids: Set[int] = set(getattr(cap, "onsite_ids", []) or []) if cap is not None else set()
        oncall_ids: Set[int] = set(getattr(cap, "oncall_ids", []) or []) if cap is not None else set()

        day_suggestions: List[AvailabilityIgnoreSlot] = []
        day_reasons: List[str] = []

        # 1) Missing candidates: suggest ignoring the missing slot(s).
        if NO_ONSITE_CANDIDATE in code_set:
            day_suggestions.append(AvailabilityIgnoreSlot(day=int(day), shift_type=ShiftType.onsite))
            day_reasons.append(NO_ONSITE_CANDIDATE)

        if NO_ONCALL_CANDIDATE in code_set:
            day_suggestions.append(AvailabilityIgnoreSlot(day=int(day), shift_type=ShiftType.oncall))
            day_reasons.append(NO_ONCALL_CANDIDATE)

        # If we already ignore something for this day, NO_SPECIALIST stops being a blocker
        # (specialist is required only when BOTH shifts are required).
        if day_suggestions:
            suggested.extend(day_suggestions)
            for r in day_reasons:
                reasons.add(r)
            continue

        # 2) FORCED_DOUBLE_SHIFT_SAME_DAY -> same single doctor is the only
        #    candidate for both shifts.  We must ignore one slot so the solver
        #    can assign the doctor to the other.  Use the same preference-based
        #    tiebreaker as NO_SPECIALIST below.
        if FORCED_DOUBLE_SHIFT_SAME_DAY in code_set:
            reasons.add(FORCED_DOUBLE_SHIFT_SAME_DAY)

            onsite_pref = _count_preferred(int(day), ShiftType.onsite, onsite_ids)
            oncall_pref = _count_preferred(int(day), ShiftType.oncall, oncall_ids)

            if onsite_pref != oncall_pref:
                ignore = ShiftType.oncall if onsite_pref > oncall_pref else ShiftType.onsite
                suggested.append(AvailabilityIgnoreSlot(day=int(day), shift_type=ignore))
                continue

            # Tie: keep onsite (fixed fallback), ignore oncall.
            suggested.append(AvailabilityIgnoreSlot(day=int(day), shift_type=ShiftType.oncall))
            continue

        # 3) Only NO_SPECIALIST -> apply new policy.
        if (NO_SPECIALIST in code_set) and (len(code_set) == 1):
            reasons.add(NO_SPECIALIST)

            onsite_pref = _count_preferred(int(day), ShiftType.onsite, onsite_ids)
            oncall_pref = _count_preferred(int(day), ShiftType.oncall, oncall_ids)

            # Rule 1: keep slot with more preferred marks
            if onsite_pref != oncall_pref:
                ignore = ShiftType.oncall if onsite_pref > oncall_pref else ShiftType.onsite
                suggested.append(AvailabilityIgnoreSlot(day=int(day), shift_type=ignore))
                continue

            onsite_total = len(onsite_ids)
            oncall_total = len(oncall_ids)

            # Rule 2: keep slot with more candidates
            if onsite_total != oncall_total:
                ignore = ShiftType.oncall if onsite_total > oncall_total else ShiftType.onsite
                suggested.append(AvailabilityIgnoreSlot(day=int(day), shift_type=ignore))
                continue

            # Rule 3: tie fallback
            suggested.append(AvailabilityIgnoreSlot(day=int(day), shift_type=ShiftType.oncall))
            continue

        # Other combinations: no suggestion (safe default).

    # Deduplicate suggestions deterministically.
    uniq = sorted({(int(s.day), str(getattr(s.shift_type, "value", s.shift_type))) for s in suggested})
    suggested_out = [AvailabilityIgnoreSlot(day=d, shift_type=ShiftType(st)) for (d, st) in uniq]

    return suggested_out, sorted(reasons)


def _suggest_ignored_slots_for_day_risk(
    *,
    day: int,
    risk_issues: List[str],
) -> tuple[List[AvailabilityIgnoreSlot], List[str]]:
    """
    Suggest ignore slots for a SINGLE day, based only on issue codes.

    This is used by availability risk views where we do NOT have full ProblemData.
    Policy here stays intentionally simple:
    - missing onsite -> ignore onsite
    - missing oncall -> ignore oncall
    - only no_specialist -> ignore oncall (fallback)
    """
    issue_set = set(risk_issues or [])
    suggested: List[AvailabilityIgnoreSlot] = []
    reasons: List[str] = []

    if NO_ONSITE_CANDIDATE in issue_set:
        suggested.append(AvailabilityIgnoreSlot(day=int(day), shift_type=ShiftType.onsite))
        reasons.append(NO_ONSITE_CANDIDATE)

    if NO_ONCALL_CANDIDATE in issue_set:
        suggested.append(AvailabilityIgnoreSlot(day=int(day), shift_type=ShiftType.oncall))
        reasons.append(NO_ONCALL_CANDIDATE)

    if not suggested and (FORCED_DOUBLE_SHIFT_SAME_DAY in issue_set):
        suggested.append(AvailabilityIgnoreSlot(day=int(day), shift_type=ShiftType.oncall))
        reasons.append(FORCED_DOUBLE_SHIFT_SAME_DAY)

    if not suggested and (NO_SPECIALIST in issue_set):
        suggested.append(AvailabilityIgnoreSlot(day=int(day), shift_type=ShiftType.oncall))
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
                raw_suggested, raw_reasons = _suggest_ignored_slots_for_day_risk(
                    day=int(d),
                    risk_issues=list(details.issues or []),
                )

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
        raw_suggested, raw_reasons = _suggest_ignored_slots_for_day_risk(
            day=int(day),
            risk_issues=list(details.issues or []),
        )

        suggested_ignored_slots = list(raw_suggested or [])
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
