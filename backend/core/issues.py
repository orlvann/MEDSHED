# backend/core/issues.py
"""
Shared issue codes and helpers for solver feasibility and availability risk.

Goals:
- Keep issue codes and default messages in one place (single source of truth).
- Avoid duplicating feasibility logic across: feasibility pre-check, CP-infeasible explain, availability UI.
- Provide availability risk helper with machine-readable reasons for UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Set

from backend.core.risk import (
    MIN_OK_DOCTORS_PER_CATEGORY,
    MIN_OK_SPECIALISTS_TOTAL,
    classify_day_risk_for_availability,
)
from backend.models.common_enums import DoctorRole, RiskLevel

# ---- Shared issue codes -------------------------------------------------------

# Feasibility (pre-check) primitives (hard / blocking signals)
NO_ONSITE_CANDIDATE = "no_onsite_candidate"
NO_ONCALL_CANDIDATE = "no_oncall_candidate"
NO_SPECIALIST = "no_specialist"
SINGLE_CANDIDATE_FOR_BOTH_ROLES = "single_candidate_for_both_roles"

# New: day is completely empty (0 candidates for onsite AND 0 for oncall)
NO_CANDIDATES_FOR_DAY = "no_candidates_for_day"

# Availability warnings (non-blocking; useful for "alert" days)
FEW_DOCTORS_TOTAL = "few_doctors_total"

# Backward-compat alias (old name kept so imports do not break)
TOO_FEW_DOCTORS_TOTAL = FEW_DOCTORS_TOTAL

# ---- Solver infeasible (post model-build) ------------------------------------

CP_INFEASIBLE = "cp_infeasible"
FORCED_DOUBLE_SHIFT_SAME_DAY = "forced_double_shift_same_day"

# ---- Head commitment issues ---------------------------------------------------

HEAD_COMMITMENT_IGNORED_SLOT = "head_commitment_ignored_slot"
HEAD_COMMITMENT_NOT_ALLOWED = "head_commitment_not_allowed"
HEAD_COMMITMENT_CONFLICT = "head_commitment_conflict"
HEAD_COMMITMENT_DOUBLE_SHIFT_SAME_DAY = "head_commitment_double_shift_same_day"

# ---- Diagnostics findings (schedule quality) ----------------------------------
# Stable codes used in backend/core/diagnostics.py findings[] (for FE mapping).
COVERAGE_MISSING_REQUIRED_SLOT = "coverage_missing_required_slot"
COVERAGE_NO_SPECIALIST_DAY = "coverage_no_specialist_day"
HARD_DOUBLE_SHIFT_SAME_DAY = "hard_double_shift_same_day"

COVERAGE_IGNORED_DAY = "coverage_ignored_day"
COVERAGE_IGNORED_SLOT = "coverage_ignored_slot"

REST_CONSECUTIVE_VIOLATION = "rest_consecutive_violation"
PREFERENCE_MISS = "preference_miss"


# ---- Default human-readable messages -----------------------------------------

FEASIBILITY_ISSUE_MESSAGES: Dict[str, str] = {
    # Feasibility pre-check
    NO_ONSITE_CANDIDATE: "No doctor is available for onsite duty on this day.",
    NO_ONCALL_CANDIDATE: "No doctor is available for on-call duty on this day.",
    NO_SPECIALIST: "No specialist is available on this day.",
    SINGLE_CANDIDATE_FOR_BOTH_ROLES: "Only one doctor is available, roles cannot be split.",
    NO_CANDIDATES_FOR_DAY: "No doctors are available for any duty on this day.",
    # Availability warnings (UI: alert)
    FEW_DOCTORS_TOTAL: "Low availability: only a small number of doctors are available in total.",
    # Head commitments (must-haves)
    HEAD_COMMITMENT_IGNORED_SLOT: "Head commitment targets an ignored slot.",
    HEAD_COMMITMENT_NOT_ALLOWED: "Head commitment is not allowed (doctor is not available for this slot).",
    HEAD_COMMITMENT_CONFLICT: "Multiple heads have a commitment for the same slot.",
    HEAD_COMMITMENT_DOUBLE_SHIFT_SAME_DAY: "A head commitment requests both onsite and oncall on the same day.",
    # CP-SAT / post-build solver outcomes
    CP_INFEASIBLE: "No schedule satisfies all hard constraints for this month (CP-SAT infeasible).",
    FORCED_DOUBLE_SHIFT_SAME_DAY: "Only one doctor can cover both shifts on this day, but double shift is forbidden.",
    # Diagnostics findings (schedule quality)
    COVERAGE_MISSING_REQUIRED_SLOT: "Required coverage slot is missing.",
    COVERAGE_NO_SPECIALIST_DAY: "No specialist is assigned on this day (onsite specialist required).",
    HARD_DOUBLE_SHIFT_SAME_DAY: "Doctor is assigned to both onsite and oncall on the same day.",
    COVERAGE_IGNORED_DAY: "Day is ignored for coverage (no required slots).",
    COVERAGE_IGNORED_SLOT: "Slot is ignored for coverage (not required).",
    REST_CONSECUTIVE_VIOLATION: "Rest rule violation: consecutive duties without required break.",
    PREFERENCE_MISS: "Preferred concrete day was not assigned.",
}

# Backward-compat alias (some modules may import ISSUE_MESSAGES)
ISSUE_MESSAGES = FEASIBILITY_ISSUE_MESSAGES


def is_forced_double_shift_same_day(
    *,
    onsite_ids: Set[int],
    oncall_ids: Set[int],
    onsite_required: bool,
    oncall_required: bool,
) -> bool:
    """
    True when BOTH shifts are required and the only onsite candidate and
    the only oncall candidate is the same single doctor.

    This is the precise case that makes the day infeasible because:
    - we require 1 onsite + 1 oncall,
    - and the same doctor cannot do both shifts on the same day.
    """
    if not (onsite_required and oncall_required):
        return False
    if len(onsite_ids) != 1 or len(oncall_ids) != 1:
        return False
    return next(iter(onsite_ids)) == next(iter(oncall_ids))


def classify_feasibility_issues_for_day(
    *,
    onsite_ids: Set[int],
    oncall_ids: Set[int],
    doctor_role_by_id: Dict[int, DoctorRole],
    onsite_required: bool,
    oncall_required: bool,
) -> List[str]:
    """
    Classify feasibility issues for a single day using REAL candidate identities.

    Why this exists:
    - counts-only logic cannot detect forced-double-shift (same single doctor for both).
    - engine (CP infeasible explain), feasibility pre-check, and availability can share this.

    Notes:
    - Only REQUIRED shifts are considered.
    - Policy: NO_SPECIALIST is emitted ONLY when BOTH shifts are required.
    """
    issues: List[str] = []

    if not onsite_required and not oncall_required:
        return issues

    # If both shifts have 0 candidates -> one clear signal (no duplicates).
    if onsite_required and oncall_required and (len(onsite_ids) == 0 and len(oncall_ids) == 0):
        issues.append(NO_CANDIDATES_FOR_DAY)
        return issues

    if onsite_required and len(onsite_ids) == 0:
        issues.append(NO_ONSITE_CANDIDATE)

    if oncall_required and len(oncall_ids) == 0:
        issues.append(NO_ONCALL_CANDIDATE)

    # Specialist rule (policy):
    # Emit NO_SPECIALIST ONLY when BOTH shifts are required.
    if onsite_required and oncall_required:
        required_union: Set[int] = set(onsite_ids) | set(oncall_ids)

        # Defensive: if union is empty, the "no candidates" logic above should have returned,
        # but keep this safe and deterministic.
        if required_union:
            has_specialist = any(doctor_role_by_id.get(int(did)) == DoctorRole.specialist for did in required_union)
            if not has_specialist:
                issues.append(NO_SPECIALIST)

    # Precise forced-double-shift case.
    if is_forced_double_shift_same_day(
        onsite_ids=onsite_ids,
        oncall_ids=oncall_ids,
        onsite_required=onsite_required,
        oncall_required=oncall_required,
    ):
        issues.append(FORCED_DOUBLE_SHIFT_SAME_DAY)
        return issues

    # Rough "roles cannot be split" based on union size (identity-aware).
    if onsite_required and oncall_required:
        if len(onsite_ids.union(oncall_ids)) == 1:
            issues.append(SINGLE_CANDIDATE_FOR_BOTH_ROLES)

    return issues


def classify_feasibility_issues_for_counts(
    *,
    total_onsite: int,
    total_oncall: int,
    total_specialists: int,
) -> List[str]:
    """
    Classify feasibility issues based on aggregate capacity counts.

    IMPORTANT LIMITATION:
    This function uses ONLY counts, so it cannot detect:
    "one doctor is available for BOTH shifts" (onsite=1, oncall=1, but same person).
    Use classify_feasibility_issues_for_day(...) when you have identities.
    """
    issues: List[str] = []

    # If both shifts have 0 candidates -> one clear signal (no duplicates).
    if total_onsite == 0 and total_oncall == 0:
        issues.append(NO_CANDIDATES_FOR_DAY)
        return issues

    if total_onsite == 0:
        issues.append(NO_ONSITE_CANDIDATE)

    if total_oncall == 0:
        issues.append(NO_ONCALL_CANDIDATE)

    if total_specialists == 0:
        issues.append(NO_SPECIALIST)

    # Rough signal based on counts only.
    if (total_onsite + total_oncall) == 1:
        issues.append(SINGLE_CANDIDATE_FOR_BOTH_ROLES)

    return issues


@dataclass
class AvailabilityRiskDetails:
    """
    Structured explanation for availability risk for a single day.

    - risk: overall RiskLevel ("ok" / "alert" / "critical")
    - issues: machine-readable issue codes explaining why the day is risky
    """

    risk: RiskLevel
    issues: List[str]


def classify_availability_risk_with_reasons(
    *,
    spec_onsite: int,
    res_onsite: int,
    spec_oncall: int,
    res_oncall: int,
    min_ok_doctors_per_category: int = MIN_OK_DOCTORS_PER_CATEGORY,
    min_ok_specialists_total: int = MIN_OK_SPECIALISTS_TOTAL,
    include_alert_issues: bool = True,
) -> AvailabilityRiskDetails:
    """
    Classify RiskLevel and issue codes for a single day based on availability counts.

    Behavior:
    - ok: issues = []
    - alert: issues may be returned (controlled by include_alert_issues)
    - critical: issues are always returned
    """
    total_specialists = spec_onsite + spec_oncall
    total_residents = res_onsite + res_oncall
    total_doctors = total_specialists + total_residents

    total_onsite = spec_onsite + res_onsite
    total_oncall = spec_oncall + res_oncall

    # 1) Risk level first (single source of truth).
    risk = classify_day_risk_for_availability(
        spec_onsite=spec_onsite,
        res_onsite=res_onsite,
        spec_oncall=spec_oncall,
        res_oncall=res_oncall,
        min_ok_doctors_per_category=min_ok_doctors_per_category,
        min_ok_specialists_total=min_ok_specialists_total,
    )

    # 2) Reasons derived from counts (useful for critical days).
    issues = classify_feasibility_issues_for_counts(
        total_onsite=total_onsite,
        total_oncall=total_oncall,
        total_specialists=total_specialists,
    )

    # 3) Warning-ish reason for alert days (low total pool).
    if total_doctors > 0 and total_doctors <= (min_ok_doctors_per_category * 2):
        if FEW_DOCTORS_TOTAL not in issues:
            issues.append(FEW_DOCTORS_TOTAL)

    # 4) Final filtering by risk level.
    if risk == RiskLevel.ok:
        issues = []

    if risk == RiskLevel.alert and not include_alert_issues:
        issues = []

    return AvailabilityRiskDetails(risk=risk, issues=issues)
