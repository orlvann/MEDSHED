# backend/core/scoring.py
"""
Shared scoring helpers and weights for the solver.

This module defines:
- one central role multiplier knob (head/specialist/resident),
- base constants for penalties and bonuses,
- helpers that apply role multipliers to selected objective categories.
"""

from backend.models.common_enums import DoctorRole, ShiftType

# ---------------------------------------------------------------------------
# Role multipliers (ONE central knob)
# ---------------------------------------------------------------------------
# We keep role multipliers in "milli-units" (1000 = 1.00x) to avoid floats in CP-SAT.
#
# Design goal:
# - Base weights define "how important a rule is in general".
# - Role multipliers define "for whom it matters more".
#
# IMPORTANT:
# - We do NOT apply role multipliers to safety/global rules like rest or fairness.
# - We apply them mostly to preference/comfort-like objectives.

ROLE_WEIGHT_MILLI = {
    "head": 2000,  # 1.60x
    DoctorRole.specialist: 1200,  # 1.20x
    DoctorRole.resident: 1000,  # 1.00x
}


def role_multiplier_milli(*, is_head: bool, role: DoctorRole) -> int:
    """
    Return a role multiplier in milli-units (1000 = 1.00x).

    Rule:
    - specialist/resident provides the base role factor
    - head multiplies ON TOP of that (head & specialist => both multipliers)
      e.g. 1.60 * 1.20 = 1.92  => 1920 milli
    """
    role_m = int(ROLE_WEIGHT_MILLI.get(role, 1000))
    head_m = int(ROLE_WEIGHT_MILLI["head"]) if is_head else 1000

    # Combine multiplicatively but keep milli-scale:
    # (role_m/1000) * (head_m/1000) = (role_m * head_m) / 1_000_000
    # We want result also in milli: multiply by 1000 => / 1000_000
    combined = (role_m * head_m) // 1000
    return int(max(1, combined))


# ---------------------------------------------------------------------------
# Role-aware categories policy
# ---------------------------------------------------------------------------

ROLE_AWARE_CATEGORIES = {
    "preferred_days",  # missing preferred concrete day
    "weekday_patterns",  # preferred/avoid weekdays
    "preferred_partners",  # requester-only weighting
    "friday_free_weekend",  # penalty
    "totals_target",  # deviation from target totals
}


def effective_weight(
    *,
    base_weight: int,
    category: str,
    is_head: bool,
    role: DoctorRole,
) -> int:
    """
    Compute an integer weight used in CP-SAT objective.

    - If category is role-aware -> multiply by role multiplier (milli) and scale back.
    - If category is role-neutral -> return base weight as-is.
    """
    if category not in ROLE_AWARE_CATEGORIES:
        return int(base_weight)

    m = role_multiplier_milli(is_head=is_head, role=role)  # e.g. 1920
    # base_weight * (m/1000)
    return int((int(base_weight) * int(m) + 500) // 1000)  # +500 for rounding


def preference_weight_for_doctor(*, is_head: bool, role: DoctorRole) -> float:
    """
    Human-friendly helper returning the role multiplier as a float.

    This is mainly for tests/debugging/docs.
    Solver code should prefer role_multiplier_milli() / effective_weight() (integer math).
    """
    return float(role_multiplier_milli(is_head=is_head, role=role)) / 1000.0


# ---------------------------------------------------------------------------
# 1. Rest-rule penalties
# ---------------------------------------------------------------------------
# Bigger = stronger preference to avoid the pattern.

REST_ONS_ONS_WEIGHT = 50
REST_ONCALL_ONCALL_WEIGHT = 20
REST_CROSS_SHIFT_SPECIALIST_WEIGHT = 40
REST_CROSS_SHIFT_RESIDENT_WEIGHT = 20


def rest_cross_shift_weight(*, role: DoctorRole) -> int:
    """
    Return the penalty weight for cross-shift rest violations:
    - specialists have stronger rest protection than residents.
    """
    if role == DoctorRole.specialist:
        return REST_CROSS_SHIFT_SPECIALIST_WEIGHT
    return REST_CROSS_SHIFT_RESIDENT_WEIGHT


# ---------------------------------------------------------------------------
# 2. Preferred days + totals penalties
# ---------------------------------------------------------------------------

# Preferred concrete day missing penalty (per preferred day that is not assigned).
# IMPORTANT:
# - This is a single BASE weight for everyone.
# - Role/head priority is applied via effective_weight(..., category="preferred_days").

PREF_DAY_MISS_BASE_WEIGHT = 2000  # 10000  # 3000  # 2000  # 1000  # 200  # 120

# Exceeding max totals (per 1 shift above max).
MAX_TOTAL_EXCESS_WEIGHT = 500  # 40
MAX_WEEKEND_EXCESS_WEIGHT = 700  # 50  # weekends a bit more important

# Deviation from target totals (per 1 shift away from target; over and under counted separately).
TARGET_TOTAL_DEVIATION_WEIGHT = 10
TARGET_WEEKEND_DEVIATION_WEIGHT = 15


# ---------------------------------------------------------------------------
# 3. Fairness by groups (specialists vs residents)
# ---------------------------------------------------------------------------

# MVP weights: a bit lower than rest rules, comparable or slightly lower than totals.
# Weekends are slightly more important because they are usually less preferred.
FAIRNESS_WEEKDAY_ONSITE_WEIGHT = 20  # 10
FAIRNESS_WEEKEND_ONSITE_WEIGHT = 28  # 14
FAIRNESS_WEEKDAY_ONCALL_WEIGHT = 8
FAIRNESS_WEEKEND_ONCALL_WEIGHT = 12


def fairness_weight(*, shift_type: ShiftType, is_weekend: bool) -> int:
    """
    Return the fairness weight for a given category.

    ```
    This helper exists only to keep objective_builder readable.
    It maps (shift_type + weekday/weekend) to the correct constant weight.
    """
    if shift_type == ShiftType.onsite:
        return FAIRNESS_WEEKEND_ONSITE_WEIGHT if is_weekend else FAIRNESS_WEEKDAY_ONSITE_WEIGHT
    return FAIRNESS_WEEKEND_ONCALL_WEIGHT if is_weekend else FAIRNESS_WEEKDAY_ONCALL_WEIGHT


# ---------------------------------------------------------------------------
# 4. Weekday pattern preferences
# ---------------------------------------------------------------------------

# Small weights (lower priority than rest/totals/fairness).
# Preferred weekdays give a small BONUS (negative term in objective),
# avoid weekdays give a small PENALTY (positive term in objective).

WEEKDAY_PREFERRED_BONUS_WEIGHT = 3
WEEKDAY_AVOID_PENALTY_WEIGHT = 4


def weekday_pattern_weight(*, kind: str) -> int:
    """
    kind: "preferred" | "avoid"
    Returns the weight used for weekday patterns.
    """
    if kind == "preferred":
        return WEEKDAY_PREFERRED_BONUS_WEIGHT
    if kind == "avoid":
        return WEEKDAY_AVOID_PENALTY_WEIGHT
    raise ValueError(f"Unknown weekday pattern kind: {kind}")


# ---------------------------------------------------------------------------
# 5. Preferred partners
# ---------------------------------------------------------------------------

# Small bonus (lower priority than rest/totals/fairness).
PREFERRED_PARTNER_BONUS_WEIGHT = 2


def preferred_partner_bonus_weight() -> int:
    """Return small bonus weight for preferred partners working the same day."""
    return PREFERRED_PARTNER_BONUS_WEIGHT


# ---------------------------------------------------------------------------
# 6. Avoid Friday if weekend off
# ---------------------------------------------------------------------------

# Small penalty (lower priority than rest/totals/fairness).
FRIDAY_WITH_FREE_WEEKEND_WEIGHT = 3


def friday_with_free_weekend_weight() -> int:
    """Return small penalty weight for working Friday when the following weekend is fully off."""
    return FRIDAY_WITH_FREE_WEEKEND_WEIGHT


# ---------------------------------------------------------------------------
# 7. Diagnostics thresholds (UI heuristics)
# ---------------------------------------------------------------------------

# Used only for rankings "happy" reasons in diagnostics:
# If a doctor's preference fulfillment is >= this threshold, we label it as "preferences_met".
HAPPY_PREFERENCES_MET_THRESHOLD_PCT = 80.0


def happy_preferences_met_threshold_pct() -> float:
    """Return threshold (percent) for labeling a doctor as 'preferences_met' in diagnostics rankings."""
    return float(HAPPY_PREFERENCES_MET_THRESHOLD_PCT)
