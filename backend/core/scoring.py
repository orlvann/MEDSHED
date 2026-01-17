# backend/core/scoring.py
"""
Shared scoring helpers and weights for the solver.

This module defines:
- role-based weights (head vs specialist vs resident),
- central constants for penalties and bonuses,
- small helper functions to keep objective_builder readable.
"""

from backend.models.common_enums import DoctorRole

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
# Rest-rule penalties (ETAP 3A)
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
# ETAP 3B: Preferred days + totals penalties (MVP)
# ---------------------------------------------------------------------------

# Preferred concrete day missing penalty (per preferred day that is not assigned).
# NOTE: We want head+specialist to SUM, so head is an "extra" added on top.

PREF_DAY_HEAD_MISS_WEIGHT = 40
PREF_DAY_SPECIALIST_MISS_WEIGHT = 30
PREF_DAY_RESIDENT_MISS_WEIGHT = 20

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

    Rules (MVP):
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
