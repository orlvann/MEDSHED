# test_feasibility_no_specialist_only_when_both_required.py
"""
Feasibility policy lock:
- NO_SPECIALIST is emitted only when BOTH shifts are required.
"""

from __future__ import annotations

import pytest

from backend.core.feasibility import analyze_problem
from backend.core.issues import NO_SPECIALIST
from backend.core.types import DoctorInput
from backend.models.common_enums import DoctorRole, ShiftType

pytestmark = [pytest.mark.solver]


def _codes(issues) -> list[str]:
    return [i.code for i in issues]


def test_no_specialist_not_emitted_when_only_one_shift_required(make_problem_data, make_preferences):
    """
    If onsite is ignored (only oncall required), we do NOT emit NO_SPECIALIST,
    even if there are no specialist candidates for oncall.
    """
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=False),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
    }

    # Specialist is unavailable for oncall; resident is available.
    prefs = make_preferences(
        doctors=doctors,
        unavailable_oncall_by_doc={1: [1]},
        unavailable_onsite_by_doc={},  # ignored anyway
    )

    problem = make_problem_data(
        days=[1],
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_days=set(),
        ignore_slots={(1, ShiftType.onsite)},  # only oncall required
    )

    issues = analyze_problem(problem)
    assert NO_SPECIALIST not in _codes(issues)


def test_no_specialist_emitted_when_both_shifts_required(make_problem_data, make_preferences):
    """
    If BOTH shifts are required and there are 0 specialist candidates across required shifts,
    we DO emit NO_SPECIALIST.
    """
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=False),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
    }

    # Specialist unavailable for BOTH shifts; only resident is available.
    prefs = make_preferences(
        doctors=doctors,
        unavailable_onsite_by_doc={1: [1]},
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
    assert NO_SPECIALIST in _codes(issues)
