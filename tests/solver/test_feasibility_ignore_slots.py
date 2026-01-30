"""
Guarantees for feasibility pre-check behavior with ignore_slots.

Main goal:
- If a slot is ignored, it is NOT required, so feasibility must NOT emit
  "no_*_candidate" for that slot.
- Specialist requirement is enforced only when BOTH shifts are required.
"""

from __future__ import annotations

import pytest

from backend.core.feasibility import analyze_problem
from backend.core.issues import (
    NO_ONCALL_CANDIDATE,
    NO_ONSITE_CANDIDATE,
    NO_SPECIALIST,
)
from backend.core.types import DoctorInput
from backend.models.common_enums import DoctorRole, ShiftType

pytestmark = [pytest.mark.solver]


def _codes(issues) -> list[str]:
    """Helper: extract issue codes."""
    return [i.code for i in issues]


def test_ignored_onsite_does_not_emit_no_onsite_candidate(make_problem_data, make_preferences):
    """
    If onsite is ignored, feasibility must NOT emit NO_ONSITE_CANDIDATE,
    even if nobody can work onsite (it is not required anyway).
    """
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=False),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
    }

    # Make everyone "unavailable" for onsite on day 1 (would be 0 candidates if it was required).
    prefs = make_preferences(
        doctors=doctors,
        unavailable_onsite_by_doc={1: [1], 2: [1]},
        unavailable_oncall_by_doc={},  # everyone can do oncall
    )

    problem = make_problem_data(
        days=[1],
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_slots={(1, ShiftType.onsite)},  # onsite is NOT required
    )

    issues = analyze_problem(problem)
    codes = _codes(issues)

    assert NO_ONSITE_CANDIDATE not in codes
    # Oncall is required and has candidates, and specialist is available oncall -> should be clean.
    assert codes == []


def test_if_only_oncall_is_required_and_has_no_candidates_we_emit_no_oncall_candidate(
    make_problem_data, make_preferences
):
    """
    If onsite is ignored but oncall is required and has 0 candidates, feasibility should emit NO_ONCALL_CANDIDATE.
    We do NOT enforce NO_SPECIALIST here, because specialist requirement is checked only when BOTH shifts are required.
    """
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=False),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
    }

    # Nobody can do oncall on day 1.
    prefs = make_preferences(
        doctors=doctors,
        unavailable_oncall_by_doc={1: [1], 2: [1]},
        unavailable_onsite_by_doc={},  # does not matter, onsite is ignored
    )

    problem = make_problem_data(
        days=[1],
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_slots={(1, ShiftType.onsite)},  # only oncall required
    )

    issues = analyze_problem(problem)
    codes = _codes(issues)

    assert NO_ONCALL_CANDIDATE in codes
    assert NO_ONSITE_CANDIDATE not in codes
    assert NO_SPECIALIST not in codes
