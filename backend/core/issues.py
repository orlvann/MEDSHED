# backend/core/issues.py
"""
Shared issue codes and helpers for solver feasibility and availability risk.

Goals:

* Keep issue codes and default messages in one place (single source of truth).
* Avoid duplicating "no_onsite / no_oncall / no_specialist / single_candidate" logic.
* Provide a richer availability risk helper with machine-readable reasons.
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

NO_ONSITE_CANDIDATE = "no_onsite_candidate"
NO_ONCALL_CANDIDATE = "no_oncall_candidate"
NO_SPECIALIST = "no_specialist"
SINGLE_CANDIDATE_FOR_BOTH_ROLES = "single_candidate_for_both_roles"
TOO_FEW_DOCTORS_TOTAL = "too_few_doctors_total"  # more general availability warning

# Default human-readable messages for feasibility issues.

FEASIBILITY_ISSUE_MESSAGES: Dict[str, str] = {
    NO_ONSITE_CANDIDATE: "No doctor is available for onsite duty on this day.",
    NO_ONCALL_CANDIDATE: "No doctor is available for on-call duty on this day.",
    NO_SPECIALIST: "No specialist is available on this day.",
    SINGLE_CANDIDATE_FOR_BOTH_ROLES: "Only one doctor is available, roles cannot be split.",
    # TOO_FEW_DOCTORS_TOTAL is more of a soft availability flag; not used in solver feasibility.
}


def classify_feasibility_issues_for_counts(
    *,
    total_onsite: int,
    total_oncall: int,
    total_specialists: int,
) -> List[str]:
    """
    Classify feasibility issues based on aggregate capacity counts.

    ```
    This mirrors the logic previously implemented in core/feasibility.py:
    - no onsite candidates        -> "no_onsite_candidate"
    - no oncall candidates        -> "no_oncall_candidate"
    - no specialist at all        -> "no_specialist"
    - only one total candidate    -> "single_candidate_for_both_roles"
    """
    issues: List[str] = []

    if total_onsite == 0:
        issues.append(NO_ONSITE_CANDIDATE)

    if total_oncall == 0:
        issues.append(NO_ONCALL_CANDIDATE)

    if total_specialists == 0:
        issues.append(NO_SPECIALIST)

    total_candidates = total_onsite + total_oncall

    if total_candidates == 1:
        issues.append(SINGLE_CANDIDATE_FOR_BOTH_ROLES)

    return issues


@dataclass
class AvailabilityRiskDetails:
    """
    Structured explanation for availability risk for a single day.

    ```
    - risk: overall RiskLevel ("ok" / "alert" / "critical"),
    - issues: machine-readable issue codes explaining why the day is critical.

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

    This combines:
    - shared feasibility issue logic (no onsite/oncall/specialist, single candidate),
    - availability-specific warning for "too few doctors in total",
    - existing RiskLevel rules from core/risk.py.

    Only critical days surface issues by default; for ok/alert days issues are empty.
    """
    total_specialists = spec_onsite + spec_oncall
    total_residents = res_onsite + res_oncall
    total_doctors = total_specialists + total_residents

    total_onsite = spec_onsite + res_onsite
    total_oncall = spec_oncall + res_oncall

    # Start from the same feasibility primitives as the solver.
    issues = classify_feasibility_issues_for_counts(
        total_onsite=total_onsite,
        total_oncall=total_oncall,
        total_specialists=total_specialists,
    )

    # Availability-specific flag: almost nobody available in total.
    if total_doctors <= 1 and SINGLE_CANDIDATE_FOR_BOTH_ROLES not in issues:
        issues.append(TOO_FEW_DOCTORS_TOTAL)

    # Compute overall RiskLevel using the shared classifier.
    risk = classify_day_risk_for_availability(
        spec_onsite=spec_onsite,
        res_onsite=res_onsite,
        spec_oncall=spec_oncall,
        res_oncall=res_oncall,
        min_ok_doctors_per_category=min_ok_doctors_per_category,
        min_ok_specialists_total=min_ok_specialists_total,
    )

    # By default, only critical days expose issues to the API.
    if risk != RiskLevel.critical:
        issues = []

    return AvailabilityRiskDetails(risk=risk, issues=issues)
