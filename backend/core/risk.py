# backend/core/risk.py
"""
Shared risk classification helpers (pure core logic).

Why this module exists:

* Keep "RiskLevel rules" in one place (single source of truth).
* Allow reuse from services (availability pre-flight) and from core diagnostics
  or publish rules later.
* No DB, no FastAPI — only pure functions.
"""

from __future__ import annotations

from backend.models.common_enums import RiskLevel

# ---- Shared risk thresholds (single source of truth) --------------------------

# These constants define when a day is considered "ok" vs "alert" vs "critical"

# based on availability counts.

# Tunable thresholds for risk classification.
# You can adjust these later after testing on real data.
MIN_OK_DOCTORS_PER_CATEGORY = 2  # how many doctors per category is considered "safe"
MIN_OK_SPECIALISTS_TOTAL = 2  # how many specialists per day is considered "safe enough"


def classify_day_risk_for_availability(
    *,
    spec_onsite: int,
    res_onsite: int,
    spec_oncall: int,
    res_oncall: int,
    onsite_required: bool = True,
    oncall_required: bool = True,
    min_ok_doctors_per_category: int = MIN_OK_DOCTORS_PER_CATEGORY,
    min_ok_specialists_total: int = MIN_OK_SPECIALISTS_TOTAL,
) -> RiskLevel:
    """
    Classify RiskLevel for a single day based on availability counts.

    IMPORTANT:
    - This function does NOT decide "critical".
      Critical is determined by hard issue codes (e.g., no candidates, forced double shift).
    - This function only decides: ok vs alert (safe-ish vs risky) when day is feasible.

    Rules (threshold-based):
    - If neither shift is required -> ok (day effectively ignored).
    - ok:
        * each REQUIRED category has enough doctors (>= min_ok_doctors_per_category)
        * and enough specialists among REQUIRED shifts:
            - if both shifts required -> >= min_ok_specialists_total
            - if only one shift required -> >= 1 specialist is "good enough" for ok
    - alert:
        * everything else (still feasible, but low capacity)
    """

    if not onsite_required and not oncall_required:
        return RiskLevel.ok

    total_onsite = spec_onsite + res_onsite
    total_oncall = spec_oncall + res_oncall

    # Count specialists only across REQUIRED shifts.
    total_specialists_required = 0
    if onsite_required:
        total_specialists_required += spec_onsite
    if oncall_required:
        total_specialists_required += spec_oncall

    # Required categories must each meet the "ok" threshold.
    if onsite_required and total_onsite < min_ok_doctors_per_category:
        return RiskLevel.alert
    if oncall_required and total_oncall < min_ok_doctors_per_category:
        return RiskLevel.alert

    # Specialists threshold depends on how many shifts are required.
    specialists_needed_for_ok = min_ok_specialists_total if (onsite_required and oncall_required) else 1
    if total_specialists_required >= specialists_needed_for_ok:
        return RiskLevel.ok

    return RiskLevel.alert
