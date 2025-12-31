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
    min_ok_doctors_per_category: int = MIN_OK_DOCTORS_PER_CATEGORY,
    min_ok_specialists_total: int = MIN_OK_SPECIALISTS_TOTAL,
) -> RiskLevel:
    """
    Classify RiskLevel for a single day based on availability counts.

    ```
    Inputs are counts of doctors available for each category and role.

    Rules:
    - critical:
        * total doctors <= 1, OR
        * no specialist at all (specialists total == 0)
    - ok:
        * enough doctors in BOTH categories (onsite + oncall),
        * and enough specialists in total
    - alert:
        * everything else
    """

    total_specialists = spec_onsite + spec_oncall
    total_residents = res_onsite + res_oncall

    total_doctors = total_specialists + total_residents

    # Critical if almost nobody is available (0 or 1 doctor total).
    if total_doctors <= 1:
        return RiskLevel.critical

    # Critical if there is no specialist at all (only residents).
    if total_specialists == 0:
        return RiskLevel.critical

    total_onsite = spec_onsite + res_onsite
    total_oncall = spec_oncall + res_oncall

    # "Ok" if both categories have "enough" doctors and enough specialists.
    if (
        total_onsite >= min_ok_doctors_per_category
        and total_oncall >= min_ok_doctors_per_category
        and total_specialists >= min_ok_specialists_total
    ):
        return RiskLevel.ok

    # All other cases are "alert" (feasible but risky).
    return RiskLevel.alert
