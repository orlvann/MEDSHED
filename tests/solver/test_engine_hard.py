# tests/solver/test_engine_hard.py
"""
Hard-constraint tests for backend/core/engine.py.

Tests covered in this file:
- test_empty_allowed_slots_returns_empty
- test_infeasible_when_required_slot_has_no_candidates
- test_infeasible_when_no_specialist_can_cover_day
- test_ok_produces_full_coverage_for_required_shifts
- test_no_doctor_has_both_shifts_on_same_day
- test_ignored_shift_is_not_assigned

Current scope:
- model building is assumed correct (HardModel input is prepared in tests),
- engine must enforce hard rules:
  - exactly one onsite and one oncall per active day (unless ignored),
  - at least one specialist per active day (among required shifts),
  - no doctor can be onsite and oncall on the same day,
  - forbidden slots do not exist as variables (allowed_slots drives x creation).

These tests should be fast and deterministic.

IMPORTANT:
- We use factories from tests/solver/conftest.py (no DB, no services).
"""

from __future__ import annotations

import pytest

from backend.core import engine
from backend.core.types import DoctorInput, SolverStatus
from backend.models.common_enums import DoctorRole, ShiftType
from tests.solver._helpers import assignments_to_map, check_hard_invariants, pretty_solution

# Mark all tests in this file as integration-level:
# - they run the real OR-Tools solver through engine.build_and_solve()
# - they do not touch DB / API (so still fast), but it's not a pure unit test
pytestmark = [pytest.mark.integration, pytest.mark.solver]


def _snapshot(model, solution) -> str:
    """
    Small helper for readable assertion messages.

    We include:
    - pretty_solution(solution)
    - + hard invariant errors, if any (even for INFEASIBLE it can be useful context)
    """
    errors = check_hard_invariants(model, solution)
    if errors:
        return f"{pretty_solution(solution)}\n\nhard_invariants_errors:\n- " + "\n- ".join(errors)
    return pretty_solution(solution)


def test_empty_allowed_slots_returns_empty(make_hard_model):
    """
    If allowed_slots is an empty dict, engine has no variables to create.
    It should return EMPTY with no assignments.
    """
    model = make_hard_model(allowed_slots={})

    solution = engine.build_and_solve(model)

    assert (
        solution.status == SolverStatus.EMPTY
    ), f"Expected EMPTY when allowed_slots is an empty dict.\n{_snapshot(model, solution)}"
    assert solution.assignments == [], f"Expected no assignments for EMPTY.\n{_snapshot(model, solution)}"


def test_infeasible_when_required_slot_has_no_candidates(make_hard_model, make_doctors, make_preferences):
    """
    If a required slot (day, shift) has zero candidates, engine forces infeasibility
    using a constraint like: 0 == 1.
    """
    doctors = make_doctors(num_specialists=1, num_residents=1, include_head=False, start_id=1)
    prefs = make_preferences(doctors=doctors)

    # One active day: 1
    # Onsite has no candidates -> required slot but empty list -> INFEASIBLE
    allowed_slots = {
        (1, ShiftType.onsite): [],
        (1, ShiftType.oncall): sorted(doctors.keys()),  # keep oncall feasible to make the cause clear
    }

    model = make_hard_model(
        days=[1],
        active_days=[1],
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_days=set(),
        ignore_slots=set(),
        allowed_slots=allowed_slots,
    )

    solution = engine.build_and_solve(model)

    assert (
        solution.status == SolverStatus.INFEASIBLE
    ), f"Expected INFEASIBLE when a required slot has zero candidates.\n{_snapshot(model, solution)}"
    assert solution.assignments == [], f"Expected no assignments for INFEASIBLE.\n{_snapshot(model, solution)}"


def test_infeasible_when_no_specialist_can_cover_day(make_hard_model, make_doctors, make_preferences):
    """
    If all candidates for required shifts are residents, the 'at least one specialist'
    hard rule should make the model infeasible.
    """
    doctors = make_doctors(num_specialists=0, num_residents=2, include_head=False, start_id=1)
    prefs = make_preferences(doctors=doctors)

    # Both shifts required, but only residents are available in both.
    resident_ids = sorted(doctors.keys())
    allowed_slots = {
        (1, ShiftType.onsite): list(resident_ids),
        (1, ShiftType.oncall): list(resident_ids),
    }

    model = make_hard_model(
        days=[1],
        active_days=[1],
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_days=set(),
        ignore_slots=set(),
        allowed_slots=allowed_slots,
    )

    solution = engine.build_and_solve(model)

    assert (
        solution.status == SolverStatus.INFEASIBLE
    ), f"Expected INFEASIBLE when no specialist can cover the required day.\n{_snapshot(model, solution)}"
    assert solution.assignments == [], f"Expected no assignments for INFEASIBLE.\n{_snapshot(model, solution)}"


def test_ok_produces_full_coverage_for_required_shifts(make_hard_model, make_doctors, make_preferences):
    """
    Feasible happy path:
    - 2 active days (1, 2)
    - at least one specialist exists
    - no ignores
    Expect:
    - OK
    - no invariant errors
    - assignments count equals number of required slots (days * 2 shifts)
    """
    doctors = make_doctors(num_specialists=1, num_residents=1, include_head=False, start_id=1)
    prefs = make_preferences(doctors=doctors)

    model = make_hard_model(
        days=[1, 2],
        active_days=[1, 2],
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_days=set(),
        ignore_slots=set(),
        # allowed_slots default would work too, but we keep it explicit and tiny:
        allowed_slots={
            (1, ShiftType.onsite): sorted(doctors.keys()),
            (1, ShiftType.oncall): sorted(doctors.keys()),
            (2, ShiftType.onsite): sorted(doctors.keys()),
            (2, ShiftType.oncall): sorted(doctors.keys()),
        },
    )

    solution = engine.build_and_solve(model)

    assert solution.status == SolverStatus.OK, f"Expected OK for a feasible tiny model.\n{_snapshot(model, solution)}"

    errors = check_hard_invariants(model, solution)
    assert errors == [], f"Hard invariants should hold for OK solution.\nErrors={errors}\n{_snapshot(model, solution)}"

    expected_slots = len(model.active_days) * 2
    assert (
        len(solution.assignments) == expected_slots
    ), f"Expected exactly {expected_slots} assignments (days * 2 required shifts).\n{_snapshot(model, solution)}"


def test_no_doctor_has_both_shifts_on_same_day(make_hard_model, make_preferences):
    """
    Build a scenario where one doctor is forced into onsite, and a different doctor
    is forced into oncall on the same day.

    This keeps the model feasible, but still proves the hard rule:
    the same doctor cannot be assigned to both shifts on the same day.
    """
    # Explicit doctors:
    # - doc 1: specialist
    # - doc 2: resident
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=False),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
    }

    prefs = make_preferences(doctors=doctors)

    # Day 1:
    # - onsite candidates: only specialist (doc 1) -> forces doc 1 onsite
    # - oncall candidates: only resident (doc 2) -> forces doc 2 oncall
    # This is feasible but still checks that engine enforces "no double shift" constraint.
    model = make_hard_model(
        days=[1],
        active_days=[1],
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_days=set(),
        ignore_slots=set(),
        allowed_slots={
            (1, ShiftType.onsite): [1],
            (1, ShiftType.oncall): [2],
        },
    )

    solution = engine.build_and_solve(model)

    assert (
        solution.status == SolverStatus.OK
    ), f"Expected OK for a feasible forced-coverage model.\n{_snapshot(model, solution)}"

    slot_map = assignments_to_map(solution)
    onsite_doc = slot_map.get((1, ShiftType.onsite))
    oncall_doc = slot_map.get((1, ShiftType.oncall))

    assert onsite_doc is not None, f"Expected an onsite assignment on day=1.\n{_snapshot(model, solution)}"
    assert oncall_doc is not None, f"Expected an oncall assignment on day=1.\n{_snapshot(model, solution)}"
    assert onsite_doc != oncall_doc, (
        "Expected different doctors for onsite and oncall on the same day (no double shift).\n"
        f"{_snapshot(model, solution)}"
    )

    errors = check_hard_invariants(model, solution)
    assert errors == [], f"Hard invariants should hold for OK solution.\nErrors={errors}\n{_snapshot(model, solution)}"


def test_ignored_shift_is_not_assigned(make_hard_model, make_doctors, make_preferences):
    """
    Bonus:
    If one shift is ignored for a given day, it should not be assigned,
    while the other required shift should still be covered.

    Scenario:
    - day 1 is active
    - onsite ignored, oncall required
    Expect:
    - OK
    - exactly 1 assignment (only oncall)
    - no assignment for (1, onsite)
    """
    doctors = make_doctors(num_specialists=1, num_residents=1, include_head=False, start_id=1)
    prefs = make_preferences(doctors=doctors)

    ignore_slots = {(1, ShiftType.onsite)}

    # Production-like behavior: ignored slot key is typically missing from allowed_slots.
    allowed_slots = {
        (1, ShiftType.oncall): sorted(doctors.keys()),
    }

    model = make_hard_model(
        days=[1],
        # active_days should include day 1, because not BOTH shifts are ignored
        active_days=[1],
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_days=set(),
        ignore_slots=ignore_slots,
        allowed_slots=allowed_slots,
    )

    solution = engine.build_and_solve(model)

    assert (
        solution.status == SolverStatus.OK
    ), f"Expected OK when one shift is ignored but the other is feasible.\n{_snapshot(model, solution)}"

    slot_map = assignments_to_map(solution)
    assert (
        1,
        ShiftType.onsite,
    ) not in slot_map, f"Expected no assignment for ignored slot (day=1, onsite).\n{_snapshot(model, solution)}"
    assert (
        1,
        ShiftType.oncall,
    ) in slot_map, f"Expected an assignment for required slot (day=1, oncall).\n{_snapshot(model, solution)}"

    assert (
        len(solution.assignments) == 1
    ), f"Expected exactly 1 assignment when only one shift is required.\n{_snapshot(model, solution)}"

    errors = check_hard_invariants(model, solution)
    assert errors == [], f"Hard invariants should hold for OK solution.\nErrors={errors}\n{_snapshot(model, solution)}"
