# backend/core/scoring.py
"""
Shared scoring helpers and weights for the solver.

This module defines:
- role-based weights (head vs specialist vs resident),
- central constants for penalties and bonuses,
- small helper functions to keep objective_builder readable.
"""

from backend.models.common_enums import DoctorRole, ShiftType

# ---------------------------------------------------------------------------
# Preference weights (generic "priority multipliers")
# ---------------------------------------------------------------------------
# These are generic multipliers for "strong preferences" (preferred_*_days).
# Heads have the highest priority, then specialists, then residents.

ROLE_PREFERENCE_WEIGHTS = {
    "head": 3.0,  # department heads (doctor.is_head == True)
    DoctorRole.specialist: 2.0,
    DoctorRole.resident: 1.0,
}


def preference_weight_for_doctor(*, is_head: bool, role: DoctorRole) -> float:
    """
    Return a numeric multiplier for satisfying a strong preference
    (preferred_onsite_days / preferred_oncall_days) of a given doctor.

    Rules:
    - Heads get the highest priority.
    - Specialists rank above residents.
    """
    if is_head:
        return ROLE_PREFERENCE_WEIGHTS["head"]
    return ROLE_PREFERENCE_WEIGHTS[role]


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
# NOTE: We want head+specialist to SUM, so head is an "extra" added on top.

PREF_DAY_HEAD_MISS_WEIGHT = 180  # 40 # 80
PREF_DAY_SPECIALIST_MISS_WEIGHT = 140  # 30 # 40
PREF_DAY_RESIDENT_MISS_WEIGHT = 100  # 20

# Exceeding max totals (per 1 shift above max).
MAX_TOTAL_EXCESS_WEIGHT = 40
MAX_WEEKEND_EXCESS_WEIGHT = 50  # weekends a bit more important

# Deviation from target totals (per 1 shift away from target; over and under counted separately).
TARGET_TOTAL_DEVIATION_WEIGHT = 10
TARGET_WEEKEND_DEVIATION_WEIGHT = 15


def preferred_day_miss_weight_for_doctor(*, is_head: bool, role: DoctorRole) -> int:
    """
    Return the penalty weight for missing a preferred concrete day
    (preferred_onsite_days / preferred_oncall_days) for a given doctor.

    Rules:
    - base part depends on role:
        * specialist -> PREF_DAY_SPECIALIST_MISS_WEIGHT
        * resident   -> PREF_DAY_RESIDENT_MISS_WEIGHT
    - if is_head=True, add PREF_DAY_HEAD_MISS_WEIGHT on top

    Examples:
    - resident (not head)          -> 20
    - specialist (not head)        -> 30
    - resident + head              -> 20 + 40 = 60
    - specialist + head            -> 30 + 40 = 70
    """
    weight = 0

    # Role part
    if role == DoctorRole.specialist:
        weight += PREF_DAY_SPECIALIST_MISS_WEIGHT
    else:
        weight += PREF_DAY_RESIDENT_MISS_WEIGHT

    # Head part (adds on top)
    if is_head:
        weight += PREF_DAY_HEAD_MISS_WEIGHT

    return weight


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
