# tests/solver/test_seeding_no_double_shift_hints.py
"""
Seeding tests: hints must never propose a double shift (onsite + oncall) for the same doctor on the same day.

Why:
- Seeding is a "suggested starting point" BEFORE CP-SAT optimization.
- It must respect the most obvious hard invariants to avoid a misleading warm-start.
"""

from __future__ import annotations

import pytest

from backend.core import seeding
from backend.core.types import DoctorInput
from backend.models.common_enums import DoctorRole, ShiftType

pytestmark = [pytest.mark.solver]


def test_seeding_never_hints_same_doctor_for_both_shifts_same_day(make_hard_model, make_problem_data, make_preferences):
    """
    Case:
    - day 1 has both required shifts
    - only one doctor exists and is allowed for both slots
    - seeding might be tempted to hint both, but it must NOT

    Expectation:
    - hints contain at most one of:
      (day=1, doc=1, onsite) OR (day=1, doc=1, oncall)
    """
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=True),
    }

    preferences = make_preferences(doctors=doctors)

    # Make head "prefer" both shifts on the same day (even if this would be invalid as a commitment).
    # We want to test seeding's internal safety, not validation.
    setattr(preferences[1], "preferred_onsite_days", [1])
    setattr(preferences[1], "preferred_oncall_days", [1])

    model = make_hard_model(
        days=[1],
        doctors=doctors,
        preferences=preferences,
        participant_doctor_ids=set(doctors.keys()),
        ignore_slots=set(),
        allowed_slots={
            (1, ShiftType.onsite): [1],
            (1, ShiftType.oncall): [1],
        },
    )

    problem = make_problem_data(
        days=[1],
        doctors=doctors,
        preferences=preferences,
        participant_doctor_ids=set(doctors.keys()),
        ignore_slots=set(),
    )

    hints = seeding.generate_initial_hints(model=model, problem=problem)

    onsite_hint = hints.get((1, 1, ShiftType.onsite), 0)
    oncall_hint = hints.get((1, 1, ShiftType.oncall), 0)

    # The key guarantee: never both.
    assert int(onsite_hint) + int(oncall_hint) <= 1
