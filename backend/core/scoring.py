# backend/core/scoring.py
"""
Shared scoring helpers and weights for the solver.

This module defines:
- role-based weights (head vs specialist vs resident),
- central constants for penalties and bonuses,
- small helper functions to keep objective_builder readable.
"""

from backend.models.common_enums import DoctorRole

# Role priority for strong preferences (calendar days "preferred_*_days")
# Heads have the highest priority, then specialists, then residents.
ROLE_PREFERENCE_WEIGHTS = {
    "head": 3.0,  # department heads (doctor.is_head == True)
    DoctorRole.specialist: 2.0,
    DoctorRole.resident: 1.0,
}


def preference_weight_for_doctor(*, is_head: bool, role: DoctorRole) -> float:
    """
    Return a numeric weight for satisfying a strong preference
    (preferred_onsite_days / preferred_oncall_days) of a given doctor.

    - Heads get the highest weight (their wishes are "almost hard").
    - Specialists rank above residents.
    """
    if is_head:
        return ROLE_PREFERENCE_WEIGHTS["head"]
    return ROLE_PREFERENCE_WEIGHTS[role]
