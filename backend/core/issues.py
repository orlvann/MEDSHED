# backend/core/issues.py
# backend/core/issues.py
"""
Shared issue codes and helpers for solver feasibility and availability risk.

Goals:
- Keep issue codes and default messages in one place (single source of truth).
- Avoid duplicating feasibility logic across: feasibility pre-check, CP-infeasible explain, availability UI.
- Provide availability risk helper with machine-readable reasons for UI.

IMPORTANT POLICY (project decision):
- We do NOT use counts-only feasibility classification (it loses identity information).
- We do NOT emit NO_CANDIDATES_FOR_DAY (legacy).
  When a day has no candidates, we report per-slot gaps:
  - no_onsite_candidate
  - no_oncall_candidate
  and (when BOTH shifts are required) also:
  - no_specialist
- RiskLevel is treated as: ok / critical (alert is being removed from the project).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Set

from backend.models.common_enums import DoctorRole, RiskLevel

# ---- Shared issue codes -------------------------------------------------------

# Feasibility (pre-check) primitives (hard / blocking signals)
NO_ONSITE_CANDIDATE = "no_onsite_candidate"
NO_ONCALL_CANDIDATE = "no_oncall_candidate"
NO_SPECIALIST = "no_specialist"
SINGLE_CANDIDATE_FOR_BOTH_ROLES = "single_candidate_for_both_roles"

# Availability warnings (kept as a code for optional UI hints; does NOT change risk level)
FEW_DOCTORS_TOTAL = "few_doctors_total"
TOO_FEW_DOCTORS_TOTAL = FEW_DOCTORS_TOTAL  # backward-compat alias

# Solver infeasible (post model-build)
CP_INFEASIBLE = "cp_infeasible"
FORCED_DOUBLE_SHIFT_SAME_DAY = "forced_double_shift_same_day"

# Head commitment issues
HEAD_COMMITMENT_IGNORED_SLOT = "head_commitment_ignored_slot"
HEAD_COMMITMENT_NOT_ALLOWED = "head_commitment_not_allowed"
HEAD_COMMITMENT_CONFLICT = "head_commitment_conflict"
HEAD_COMMITMENT_DOUBLE_SHIFT_SAME_DAY = "head_commitment_double_shift_same_day"

# Diagnostics findings (schedule quality)
COVERAGE_MISSING_REQUIRED_SLOT = "coverage_missing_required_slot"
COVERAGE_NO_SPECIALIST_DAY = "coverage_no_specialist_day"
HARD_DOUBLE_SHIFT_SAME_DAY = "hard_double_shift_same_day"

# NOTE:
# Even if we remove ignore_days from the flow, we can still keep these codes
# because "both slots ignored" is still a meaningful concept for diagnostics/history.
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
    # Availability warnings
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

    Notes:
    - Only REQUIRED shifts are considered.
    - Policy: NO_SPECIALIST is emitted ONLY when BOTH shifts are required.
      (If one shift is ignored, we do NOT require a specialist for that day.)
    - Policy: we do NOT emit a "whole-day" code like NO_CANDIDATES_FOR_DAY.
      We emit per-slot issues (NO_ONSITE_CANDIDATE / NO_ONCALL_CANDIDATE),
      and NO_SPECIALIST may also be emitted depending on the rule above.
    """
    issues: List[str] = []

    if not onsite_required and not oncall_required:
        return issues

    # Per-slot gaps first (deterministic order).
    if onsite_required and len(onsite_ids) == 0:
        issues.append(NO_ONSITE_CANDIDATE)

    if oncall_required and len(oncall_ids) == 0:
        issues.append(NO_ONCALL_CANDIDATE)

    # Specialist rule (union of REQUIRED candidates).
    if onsite_required and oncall_required:
        required_union: Set[int] = set(onsite_ids) | set(oncall_ids)
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


@dataclass
class AvailabilityRiskDetails:
    """
    Structured explanation for availability risk for a single day.

    - risk: overall RiskLevel ("ok" / "critical")
    - issues: machine-readable issue codes explaining why the day is risky
    """

    risk: RiskLevel
    issues: List[str]


def classify_availability_risk_with_reasons(
    *,
    onsite_ids: Set[int],
    oncall_ids: Set[int],
    doctor_role_by_id: Dict[int, DoctorRole],
    onsite_required: bool,
    oncall_required: bool,
) -> AvailabilityRiskDetails:
    """
    Compute availability risk + machine-readable reasons (ID-aware).

    FINAL BUSINESS POLICY:
    - RiskLevel is: ok / critical.
    - critical when:
      1) any REQUIRED slot has zero candidates, OR
      2) among candidates for the day (union of REQUIRED slots) there is no specialist.

    Notes:
    - For "business-required" mode (heatmap + prepublish):
      onsite_required=True and oncall_required=True for every day.
    - For "solver-required" mode (generate gatekeeper + postmortem):
      required flags must respect ignore_slots (slot ignored => not required).
    """
    issues: List[str] = []

    if onsite_required and len(onsite_ids) == 0:
        issues.append(NO_ONSITE_CANDIDATE)

    if oncall_required and len(oncall_ids) == 0:
        issues.append(NO_ONCALL_CANDIDATE)

    # Specialist rule: only when BOTH shifts are required.
    if onsite_required and oncall_required:
        required_union: Set[int] = set(onsite_ids) | set(oncall_ids)
        has_specialist = any(doctor_role_by_id.get(int(did)) == DoctorRole.specialist for did in required_union)
        if not has_specialist:
            issues.append(NO_SPECIALIST)

    risk = RiskLevel.ok
    if issues:
        risk = RiskLevel.critical

    return AvailabilityRiskDetails(risk=risk, issues=issues)
