# tests/solver/test_objective_preferred_days.py
"""
Soft-objective tests for ETAP 3B preferred days only:
- preferred concrete days (preferred_onsite_days / preferred_oncall_days)

We verify that:
- If multiple feasible schedules exist, the solver prefers the one
  with lower preferred-days penalty (miss penalties).
- Head+specialist weight is higher than plain specialist if they compete.

Design notes:
- No DB / services.
- We keep scenarios tiny.
- We use single-day schedules to avoid rest rules completely.
"""

from __future__ import annotations

import pytest

from backend.core import engine, scoring
from backend.core.types import DoctorInput, SolverStatus
from backend.models.common_enums import DoctorRole, ShiftType


def _get_assigned_doctor(solution, *, day: int, shift_type: ShiftType) -> int | None:
    """Return doctor_id assigned to (day, shift_type), or None if not present."""
    for a in solution.assignments:
        if a.day == day and a.shift_type == shift_type:
            return a.doctor_id
    return None


@pytest.mark.unit
def test_preferred_day_weight_sums_for_head_specialist():
    """
    Regression test for scoring.preferred_day_miss_weight_for_doctor().

    We want weights to SUM when a doctor is both head and specialist:
    head (40) + specialist (30) = 70
    """
    w = scoring.preferred_day_miss_weight_for_doctor(is_head=True, role=DoctorRole.specialist)
    assert w == scoring.PREF_DAY_HEAD_MISS_WEIGHT + scoring.PREF_DAY_SPECIALIST_MISS_WEIGHT


@pytest.mark.integration
def test_solver_prefers_satisfying_preferred_onsite_day(make_hard_model, make_doctors, make_preferences):
    """
    Integration test.

    Single day => no rest rules.
    Two specialists can do onsite; oncall is fixed to resident.
    One specialist prefers onsite on this day.

    Expect:
    - solver assigns onsite to the preferred specialist if possible.
    """
    year = 2026
    month = 1
    days = [1]

    doctors = make_doctors(num_specialists=2, num_residents=1, include_head=False, start_id=1)
    specialist_ids = [doc_id for doc_id, d in doctors.items() if d.role == DoctorRole.specialist]
    resident_id = [doc_id for doc_id, d in doctors.items() if d.role == DoctorRole.resident][0]

    prefs = make_preferences(doctors=doctors)

    preferred_doc = specialist_ids[0]
    prefs[preferred_doc].preferred_onsite_days = [1]

    allowed_slots = {
        (1, ShiftType.onsite): list(specialist_ids),
        (1, ShiftType.oncall): [resident_id],
    }

    model = make_hard_model(
        year=year,
        month=month,
        days=days,
        active_days=days,
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        allowed_slots=allowed_slots,
    )

    solution = engine.build_and_solve(model)
    assert solution.status == SolverStatus.OK

    got_onsite = _get_assigned_doctor(solution, day=1, shift_type=ShiftType.onsite)
    assert got_onsite == preferred_doc, (
        "Expected solver to assign preferred doctor to preferred onsite day.\n"
        f"got_onsite={got_onsite} preferred_doc={preferred_doc}\n"
        f"assignments={solution.assignments}"
    )


@pytest.mark.integration
def test_solver_prefers_head_specialist_when_both_prefer_same_day(make_hard_model, make_preferences):
    """
    Integration test.

    One day => no rest rules.
    Two specialists compete for single onsite slot and BOTH prefer it.
    One is head+specialist, so missing her preference is more expensive.

    Expect:
    - solver assigns onsite to head+specialist.
    """
    year = 2026
    month = 1
    days = [1]

    doctors = {
        10: DoctorInput(id=10, role=DoctorRole.specialist, is_head=True),
        11: DoctorInput(id=11, role=DoctorRole.specialist, is_head=False),
        20: DoctorInput(id=20, role=DoctorRole.resident, is_head=False),  # oncall fixed
    }

    prefs = make_preferences(doctors=doctors)

    prefs[10].preferred_onsite_days = [1]
    prefs[11].preferred_onsite_days = [1]

    allowed_slots = {
        (1, ShiftType.onsite): [10, 11],
        (1, ShiftType.oncall): [20],
    }

    model = make_hard_model(
        year=year,
        month=month,
        days=days,
        active_days=days,
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        allowed_slots=allowed_slots,
    )

    solution = engine.build_and_solve(model)
    assert solution.status == SolverStatus.OK

    got_onsite = _get_assigned_doctor(solution, day=1, shift_type=ShiftType.onsite)
    assert got_onsite == 10, (
        "Expected solver to choose head+specialist when both prefer the same onsite day.\n"
        f"got_onsite={got_onsite}\n"
        f"assignments={solution.assignments}"
    )
