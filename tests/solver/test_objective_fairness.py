# tests/solver/test_objective_fairness.py
"""
Soft-objective tests for role-group fairness.

We verify that:
- If multiple feasible schedules exist and other objectives do not differentiate them,
  the solver prefers the schedule with lower fairness penalty.

Design choices:
- No DB / services.
- Tiny models.
- We use NON-consecutive days to fully avoid rest-rule penalties.
  (objective_builder rest rules only look at consecutive pairs d and d+1)
"""

from __future__ import annotations

import pytest

from backend.core import engine, scoring
from backend.core.types import SolverStatus
from backend.models.common_enums import DoctorRole, ShiftType
from tests.solver._helpers import assignments_to_map, pretty_solution

pytestmark = [pytest.mark.solver]


def _get_doc(slot_map: dict[tuple[int, ShiftType], int], *, day: int, shift: ShiftType) -> int | None:
    """Return assigned doctor_id for (day, shift) or None."""
    return slot_map.get((int(day), shift))


@pytest.mark.unit
def test_scoring_fairness_weight_mapping():
    """
    Unit regression test:
    This test checks that scoring.fairness_weight(...) returns the correct constant
    from scoring.py for each case:
    - onsite weekday
    - onsite weekend
    - oncall weekday
    - oncall weekend

    Why do we need it?
    Because fairness_weight() is a small "routing" function (it chooses a constant).
    If someone accidentally swaps weekend/weekday or onsite/oncall inside that function,
    the solver behavior changes silently. This test catches that mistake early.
    """
    assert (
        scoring.fairness_weight(shift_type=ShiftType.onsite, is_weekend=False) == scoring.FAIRNESS_WEEKDAY_ONSITE_WEIGHT
    )
    assert (
        scoring.fairness_weight(shift_type=ShiftType.onsite, is_weekend=True) == scoring.FAIRNESS_WEEKEND_ONSITE_WEIGHT
    )
    assert (
        scoring.fairness_weight(shift_type=ShiftType.oncall, is_weekend=False) == scoring.FAIRNESS_WEEKDAY_ONCALL_WEIGHT
    )
    assert (
        scoring.fairness_weight(shift_type=ShiftType.oncall, is_weekend=True) == scoring.FAIRNESS_WEEKEND_ONCALL_WEIGHT
    )


def test_solver_prefers_more_even_distribution_within_specialists_and_residents(
    make_hard_model, make_doctors, make_preferences
):
    """
    Integration test.

    We build a scenario where:
    - There are TWO specialists and TWO residents (so fairness groups have size 2).
    - We schedule TWO NON-consecutive WEEKDAYS (to avoid rest penalties completely).
    - Onsite can be done only by specialists; oncall only by residents.
      (this keeps the specialist hard rule satisfied, and avoids cross-role mixing)

    Without fairness:
    - Many solutions are equally good (e.g. same specialist gets onsite twice vs split).
    With fairness:
    - The solver should prefer splitting counts evenly in each role group:
      specialists: onsite totals should be 1 and 1 (instead of 2 and 0)
      residents:  oncall totals should be 1 and 1 (instead of 2 and 0)

    We do NOT require a specific doctor ID to be chosen on a given day:
    We only require "not the same doctor twice" within each category.
    """
    year = 2026
    month = 1

    # Use two non-consecutive weekdays in Jan 2026:
    # Jan 6, 2026 = Tuesday
    # Jan 8, 2026 = Thursday
    days = [6, 8]

    doctors = make_doctors(num_specialists=2, num_residents=2, include_head=False, start_id=1)
    prefs = make_preferences(doctors=doctors)

    specialist_ids = sorted([doc_id for doc_id, d in doctors.items() if d.role == DoctorRole.specialist])
    resident_ids = sorted([doc_id for doc_id, d in doctors.items() if d.role == DoctorRole.resident])

    # Allowed slots:
    # - onsite: only specialists
    # - oncall: only residents
    allowed_slots = {
        (6, ShiftType.onsite): list(specialist_ids),
        (6, ShiftType.oncall): list(resident_ids),
        (8, ShiftType.onsite): list(specialist_ids),
        (8, ShiftType.oncall): list(resident_ids),
    }

    model = make_hard_model(
        year=year,
        month=month,
        days=days,
        active_days=days,
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_slots=set(),
        allowed_slots=allowed_slots,
    )

    solution = engine.build_and_solve(model)
    assert solution.status == SolverStatus.OK, f"Expected OK.\n{pretty_solution(solution)}"

    slot_map = assignments_to_map(solution)

    ons_6 = _get_doc(slot_map, day=6, shift=ShiftType.onsite)
    ons_8 = _get_doc(slot_map, day=8, shift=ShiftType.onsite)
    onc_6 = _get_doc(slot_map, day=6, shift=ShiftType.oncall)
    onc_8 = _get_doc(slot_map, day=8, shift=ShiftType.oncall)

    assert ons_6 in specialist_ids and ons_8 in specialist_ids, (
        "Expected onsite to be assigned to specialists only.\n"
        f"ons_6={ons_6} ons_8={ons_8} specialist_ids={specialist_ids}\n"
        f"{pretty_solution(solution)}"
    )
    assert onc_6 in resident_ids and onc_8 in resident_ids, (
        "Expected oncall to be assigned to residents only.\n"
        f"onc_6={onc_6} onc_8={onc_8} resident_ids={resident_ids}\n"
        f"{pretty_solution(solution)}"
    )

    # This is the key fairness assertion:
    # With fairness objective, the solver should avoid giving BOTH onsite shifts
    # to the same specialist (2 vs 0 distribution) if it can split (1 vs 1).
    assert ons_6 != ons_8, (
        "Expected fairness objective to split onsite weekday shifts across specialists.\n"
        f"ons_6={ons_6} ons_8={ons_8}\n"
        f"{pretty_solution(solution)}"
    )

    # Same for oncall shifts among residents:
    assert onc_6 != onc_8, (
        "Expected fairness objective to split oncall weekday shifts across residents.\n"
        f"onc_6={onc_6} onc_8={onc_8}\n"
        f"{pretty_solution(solution)}"
    )


def test_solver_prefers_split_when_targets_are_zero_due_to_quadratic_penalty(
    make_hard_model, make_doctors, make_preferences
):
    """
    Integration test (quadratic penalty proof).

    Goal:
    Show why we use an ESCALATING (quadratic) penalty for fairness deviations.

    Setup:
    - 2 specialists in the same fairness group.
    - 2 non-consecutive WEEKDAYS (no rest penalties).
    - Onsite can be done only by specialists.
    - Oncall is fixed to a single resident (so resident fairness group size = 1 -> ignored).

    Key trick:
    We set target_onsite_total=0 for BOTH specialists.
    That means each specialist "expects" 0 onsite shifts.

    Two feasible distributions for 2 onsite shifts:
    - A) (2, 0) -> abs deviations: (2, 0)
    - B) (1, 1) -> abs deviations: (1, 1)

    If fairness was linear, both would have the same total deviation (2).
    With quadratic penalty, (2,0) costs 4, while (1,1) costs 2 -> solver prefers split.
    """
    year = 2026
    month = 1
    days = [6, 8]  # Tue + Thu (non-consecutive weekdays)

    doctors = make_doctors(num_specialists=2, num_residents=1, include_head=False, start_id=1)
    prefs = make_preferences(doctors=doctors)

    specialist_ids = sorted([doc_id for doc_id, d in doctors.items() if d.role == DoctorRole.specialist])
    resident_id = [doc_id for doc_id, d in doctors.items() if d.role == DoctorRole.resident][0]

    # Both specialists "expect" 0 onsite total (for fairness expected=target when set).
    for sid in specialist_ids:
        prefs[sid].target_onsite_total = 0

    allowed_slots = {
        (6, ShiftType.onsite): list(specialist_ids),
        (6, ShiftType.oncall): [resident_id],
        (8, ShiftType.onsite): list(specialist_ids),
        (8, ShiftType.oncall): [resident_id],
    }

    model = make_hard_model(
        year=year,
        month=month,
        days=days,
        active_days=days,
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_slots=set(),
        allowed_slots=allowed_slots,
    )

    solution = engine.build_and_solve(model)
    assert solution.status == SolverStatus.OK, f"Expected OK.\n{pretty_solution(solution)}"

    slot_map = assignments_to_map(solution)
    ons_6 = _get_doc(slot_map, day=6, shift=ShiftType.onsite)
    ons_8 = _get_doc(slot_map, day=8, shift=ShiftType.onsite)

    assert ons_6 in specialist_ids and ons_8 in specialist_ids, (
        "Expected onsite to be assigned to specialists only.\n"
        f"ons_6={ons_6} ons_8={ons_8} specialist_ids={specialist_ids}\n"
        f"{pretty_solution(solution)}"
    )

    # With quadratic fairness penalty, solver should avoid (2,0) and prefer (1,1).
    assert ons_6 != ons_8, (
        "Expected quadratic fairness penalty to prefer splitting onsite shifts (1,1) over concentrating (2,0).\n"
        f"ons_6={ons_6} ons_8={ons_8}\n"
        f"{pretty_solution(solution)}"
    )


def test_solver_respects_different_targets_and_does_not_force_equal_split(
    make_hard_model, make_doctors, make_preferences
):
    """
    Integration test (different targets).

    Goal:
    If doctors set different targets, fairness should not fight that.
    Expected behavior:
    - if a doctor has target_* set -> expected = target
    - otherwise -> expected = group average

    Setup:
    - 2 specialists, 2 weekday days (onsite required twice).
    - Specialist A target_onsite_total = 2 (wants both onsite shifts)
    - Specialist B target_onsite_total = 0

    Best solution should assign BOTH onsite shifts to specialist A,
    because it matches targets exactly (0 deviation for both).
    """
    year = 2026
    month = 1
    days = [6, 8]  # Tue + Thu (non-consecutive weekdays)

    doctors = make_doctors(num_specialists=2, num_residents=1, include_head=False, start_id=1)
    prefs = make_preferences(doctors=doctors)

    specialist_ids = sorted([doc_id for doc_id, d in doctors.items() if d.role == DoctorRole.specialist])
    resident_id = [doc_id for doc_id, d in doctors.items() if d.role == DoctorRole.resident][0]

    a = specialist_ids[0]
    b = specialist_ids[1]

    prefs[a].target_onsite_total = 2
    prefs[b].target_onsite_total = 0

    allowed_slots = {
        (6, ShiftType.onsite): list(specialist_ids),
        (6, ShiftType.oncall): [resident_id],
        (8, ShiftType.onsite): list(specialist_ids),
        (8, ShiftType.oncall): [resident_id],
    }

    model = make_hard_model(
        year=year,
        month=month,
        days=days,
        active_days=days,
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_slots=set(),
        allowed_slots=allowed_slots,
    )

    solution = engine.build_and_solve(model)
    assert solution.status == SolverStatus.OK, f"Expected OK.\n{pretty_solution(solution)}"

    slot_map = assignments_to_map(solution)
    ons_6 = _get_doc(slot_map, day=6, shift=ShiftType.onsite)
    ons_8 = _get_doc(slot_map, day=8, shift=ShiftType.onsite)

    assert (
        (ons_6, ons_8) == (a, a) or (ons_6, ons_8) == (b, b) or (ons_6, ons_8) == (a, b) or (ons_6, ons_8) == (b, a)
    ), (
        "Sanity check: onsite assignments should be valid specialist IDs.\n"
        f"ons_6={ons_6} ons_8={ons_8} specialist_ids={specialist_ids}\n"
        f"{pretty_solution(solution)}"
    )

    # The intended behavior: both onsite shifts should go to the doctor who targeted 2.
    assert ons_6 == a and ons_8 == a, (
        "Expected solver to respect different targets: doctor with target=2 should get both onsite shifts.\n"
        f"targets: doc{a}=2 doc{b}=0\n"
        f"got: ons_6={ons_6} ons_8={ons_8}\n"
        f"{pretty_solution(solution)}"
    )
