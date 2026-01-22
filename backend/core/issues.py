# backend/core/issues.py
"""
Shared issue codes and helpers for solver feasibility and availability risk.

Goals:
- Keep issue codes and default messages in one place (single source of truth).
- Avoid duplicating "no_onsite / no_oncall / no_specialist / single_candidate" logic.
- Provide a richer availability risk helper with machine-readable reasons.

NOTE:
Despite the historical name `FEASIBILITY_ISSUE_MESSAGES`, this module now stores
messages for multiple phases:
- feasibility pre-check (cheap counts),
- seeding validation (head commitments),
- post model-build solver failures (CP-SAT infeasible, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from backend.core.risk import (
    MIN_OK_DOCTORS_PER_CATEGORY,
    MIN_OK_SPECIALISTS_TOTAL,
    classify_day_risk_for_availability,
)
from backend.models.common_enums import RiskLevel

# ---- Shared issue codes -------------------------------------------------------

# Feasibility (pre-check) primitives
NO_ONSITE_CANDIDATE = "no_onsite_candidate"
NO_ONCALL_CANDIDATE = "no_oncall_candidate"
NO_SPECIALIST = "no_specialist"
SINGLE_CANDIDATE_FOR_BOTH_ROLES = "single_candidate_for_both_roles"

# Availability risk (warning-ish, not always a hard stop)
TOO_FEW_DOCTORS_TOTAL = "too_few_doctors_total"

# ---- Solver infeasible (post model-build) ------------------------------------

# Generic "CP-SAT found no feasible schedule"
CP_INFEASIBLE = "cp_infeasible"

# More specific day-level reason that can be emitted by a deeper check:
# "only one unique doctor can cover both shifts, but double shift is forbidden"
FORCED_DOUBLE_SHIFT_SAME_DAY = "forced_double_shift_same_day"

# ---- Head commitment issues (must-have head preferred slots) ------------------

HEAD_COMMITMENT_IGNORED_SLOT = "head_commitment_ignored_slot"
HEAD_COMMITMENT_NOT_ALLOWED = "head_commitment_not_allowed"
HEAD_COMMITMENT_CONFLICT = "head_commitment_conflict"
HEAD_COMMITMENT_DOUBLE_SHIFT_SAME_DAY = "head_commitment_double_shift_same_day"

# ---- Default human-readable messages -----------------------------------------

# Historical name kept for compatibility (other modules import it).
# It contains messages for ALL issue codes, not only feasibility.
FEASIBILITY_ISSUE_MESSAGES: Dict[str, str] = {
    # Feasibility pre-check
    NO_ONSITE_CANDIDATE: "No doctor is available for onsite duty on this day.",
    NO_ONCALL_CANDIDATE: "No doctor is available for on-call duty on this day.",
    NO_SPECIALIST: "No specialist is available on this day.",
    SINGLE_CANDIDATE_FOR_BOTH_ROLES: "Only one doctor is available, roles cannot be split.",
    # Availability risk (can be shown as warning in UI)
    TOO_FEW_DOCTORS_TOTAL: "Very low availability: too few doctors are available in total.",
    # Head commitments (must-haves)
    HEAD_COMMITMENT_IGNORED_SLOT: "Head commitment targets an ignored slot.",
    HEAD_COMMITMENT_NOT_ALLOWED: "Head commitment is not allowed (doctor is not available for this slot).",
    HEAD_COMMITMENT_CONFLICT: "Multiple heads have a commitment for the same slot.",
    HEAD_COMMITMENT_DOUBLE_SHIFT_SAME_DAY: "A head commitment requests both onsite and oncall on the same day.",
    # CP-SAT / post-build solver outcomes
    CP_INFEASIBLE: "No schedule satisfies all hard constraints for this month (CP-SAT infeasible).",
    FORCED_DOUBLE_SHIFT_SAME_DAY: "Only one doctor can cover both shifts on this day, but double shift is forbidden.",
}

# Optional clearer alias (nice for new code; old name still works).
ISSUE_MESSAGES = FEASIBILITY_ISSUE_MESSAGES


def classify_feasibility_issues_for_counts(
    *,
    total_onsite: int,
    total_oncall: int,
    total_specialists: int,
) -> List[str]:
    """
    Classify feasibility issues based on aggregate capacity counts.

    IMPORTANT LIMITATION:
    This function uses ONLY counts, so it cannot detect the case:
    "one doctor is available for BOTH shifts" (onsite=1, oncall=1, but same person).
    That more specific case must be detected by a deeper check that knows identities.
    """
    issues: List[str] = []

    if total_onsite == 0:
        issues.append(NO_ONSITE_CANDIDATE)

    if total_oncall == 0:
        issues.append(NO_ONCALL_CANDIDATE)

    if total_specialists == 0:
        issues.append(NO_SPECIALIST)

    # This is a very rough signal based on counts only.
    total_candidates = total_onsite + total_oncall
    if total_candidates == 1:
        issues.append(SINGLE_CANDIDATE_FOR_BOTH_ROLES)

    return issues


@dataclass
class AvailabilityRiskDetails:
    """
    Structured explanation for availability risk for a single day.

    - risk: overall RiskLevel ("ok" / "alert" / "critical")
    - issues: machine-readable issue codes explaining why the day is critical

    For non-critical days, issues is typically an empty list.
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
) -> AvailabilityRiskDetails:
    """
    Classify RiskLevel and issue codes for a single day based on availability counts.

    Only critical days surface issues by default; for ok/alert days issues are empty.
    """
    total_specialists = spec_onsite + spec_oncall
    total_residents = res_onsite + res_oncall
    total_doctors = total_specialists + total_residents

    total_onsite = spec_onsite + res_onsite
    total_oncall = spec_oncall + res_oncall

    issues = classify_feasibility_issues_for_counts(
        total_onsite=total_onsite,
        total_oncall=total_oncall,
        total_specialists=total_specialists,
    )

    # Availability-specific flag: almost nobody available in total.
    # (Keep it separate from SINGLE_CANDIDATE_FOR_BOTH_ROLES which is a feasibility hint.)
    if total_doctors <= 1 and SINGLE_CANDIDATE_FOR_BOTH_ROLES not in issues:
        issues.append(TOO_FEW_DOCTORS_TOTAL)

    risk = classify_day_risk_for_availability(
        spec_onsite=spec_onsite,
        res_onsite=res_onsite,
        spec_oncall=spec_oncall,
        res_oncall=res_oncall,
        min_ok_doctors_per_category=min_ok_doctors_per_category,
        min_ok_specialists_total=min_ok_specialists_total,
    )

    if risk != RiskLevel.critical:
        issues = []

    return AvailabilityRiskDetails(risk=risk, issues=issues)
