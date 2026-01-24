"""
Feasibility pre-check: forced double shift detection (identity-based).

Goal:
- Detect the real "forced double shift" case:
  onsite has exactly one candidate AND oncall has exactly one candidate
  AND it is the same doctor -> infeasible because double shift is forbidden.
"""

from __future__ import annotations

import pytest

from backend.core.feasibility import analyze_problem
from backend.core.issues import FORCED_DOUBLE_SHIFT_SAME_DAY
from backend.core.types import DoctorInput
from backend.models.common_enums import DoctorRole

pytestmark = [pytest.mark.solver]


def _codes(issues) -> list[str]:
    return [i.code for i in issues]


def test_forced_double_shift_same_doctor_is_detected(make_problem_data, make_preferences):
    """
    Day 1:
    - BOTH shifts required.
    - Only doctor 1 can do onsite and oncall.
    Expect:
    - FORCED_DOUBLE_SHIFT_SAME_DAY is emitted.
    """
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=False),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
    }

    # Make doctor 2 unavailable for BOTH shifts on day 1.
    prefs = make_preferences(
        doctors=doctors,
        unavailable_onsite_by_doc={2: [1]},
        unavailable_oncall_by_doc={2: [1]},
    )

    problem = make_problem_data(
        days=[1],
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_days=set(),
        ignore_slots=set(),  # both required
    )

    issues = analyze_problem(problem)
    codes = _codes(issues)

    assert FORCED_DOUBLE_SHIFT_SAME_DAY in codes


def test_forced_double_shift_not_emitted_when_candidates_are_different(make_problem_data, make_preferences):
    """
    Day 1:
    - BOTH shifts required.
    - Exactly one onsite candidate (doc 1) and one oncall candidate (doc 2),
      but they are different doctors -> NOT forced double.
    Expect:
    - No FORCED_DOUBLE_SHIFT_SAME_DAY
    """
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=False),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
    }

    # Doctor 1 can only do onsite; doctor 2 can only do oncall.
    prefs = make_preferences(
        doctors=doctors,
        unavailable_onsite_by_doc={2: [1]},
        unavailable_oncall_by_doc={1: [1]},
    )

    problem = make_problem_data(
        days=[1],
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_days=set(),
        ignore_slots=set(),  # both required
    )

    issues = analyze_problem(problem)
    codes = _codes(issues)

    assert FORCED_DOUBLE_SHIFT_SAME_DAY not in codes
