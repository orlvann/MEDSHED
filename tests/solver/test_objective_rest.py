# tests/solver/test_objective_rest.py
"""
Soft-objective tests for rest rules.

We verify that adding rest-rule penalties changes which FEASIBLE solution
is chosen by the solver (the solver should prefer lower-penalty schedules).

We also verify the weekend exception:
- Sat->Sun cross-shift is NOT penalized when allow_weekend_consecutive_onsite_oncall=True.

Tests covered in this file:
- test_solver_prefers_lower_rest_penalty_solution (integration)
- test_cross_shift_penalty_is_higher_for_specialist_than_resident (offline/unit-ish)
- test_weekend_exception_true_skips_cross_penalty (offline/unit-ish)
- test_weekend_exception_false_applies_cross_penalty (offline/unit-ish)
- test_objective_builder_is_defensive_when_x_missing_in_inactive_days (integration/defensive)
- test_objective_builder_returns_zero_var_when_participants_empty (unit-ish regression)

Key behaviors enforced:
- Soft objective MUST NOT change feasibility (hard rules decide OK vs INFEASIBLE).
- Among multiple feasible schedules, the solver should prefer the one with lower rest penalty.
- Objective builder must be defensive: missing decision variables (x) must not crash it.

IMPORTANT:
- We use factories from tests/solver/conftest.py (no DB, no services).
- For readable failure messages we use solution_snapshot(model, solution).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from ortools.sat.python import cp_model

from backend.core import engine, objective_builder
from backend.core.types import DoctorInput, SolverAssignment, SolverStatus
from backend.models.common_enums import DoctorRole, ShiftType

from ._helpers import compute_rest_penalty_offline, count_rest_violations_offline, solution_snapshot

pytestmark = [pytest.mark.solver]


# --------------------------------------------------------------------------------------
# 1) Integration test: solver should prefer lower rest penalty among feasible solutions
# --------------------------------------------------------------------------------------


def test_solver_prefers_lower_rest_penalty_solution(make_hard_model, make_doctors, make_preferences):
    """
    INTEGRATION TEST.

    We create a tiny 2-day scenario with multiple feasible onsite choices.
    Oncall is fixed to the same doctor both days (unavoidable oncall->oncall penalty),
    while onsite can be:
    - SAME specialist both days  -> adds extra ons->ons penalty (worse)
    - DIFFERENT specialists      -> avoids ons->ons penalty (better)

    Expectation:
    - solver returns OK (hard constraints are satisfied),
    - solver picks an onsite pattern with LOWER total rest penalty.
    """
    year = 2026
    month = 1
    days = [1, 2]  # consecutive -> rest rules apply on (1 -> 2)

    # Doctors:
    # - 2 specialists (so onsite can alternate)
    # - 1 resident (fixed oncall both days)
    doctors = make_doctors(num_specialists=2, num_residents=1, include_head=False, start_id=1)
    specialist_ids = [doc_id for doc_id, d in doctors.items() if d.role == DoctorRole.specialist]
    resident_ids = [doc_id for doc_id, d in doctors.items() if d.role == DoctorRole.resident]

    assert len(specialist_ids) == 2, "Test setup requires exactly 2 specialists."
    assert len(resident_ids) == 1, "Test setup requires exactly 1 resident."

    resident_id = resident_ids[0]
    prefs = make_preferences(doctors=doctors)

    # Allowed slots:
    # - Oncall: only the resident can do it on both days (forces oncall->oncall penalty)
    # - Onsite: either specialist can do it (solver chooses)
    allowed_slots = {
        (1, ShiftType.onsite): list(specialist_ids),
        (2, ShiftType.onsite): list(specialist_ids),
        (1, ShiftType.oncall): [resident_id],
        (2, ShiftType.oncall): [resident_id],
    }

    model = make_hard_model(
        year=year,
        month=month,
        days=days,
        active_days=days,  # both days are scheduled
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_slots=set(),
        allowed_slots=allowed_slots,
    )

    solution = engine.build_and_solve(model)
    assert (
        solution.status == SolverStatus.OK
    ), f"Expected OK (feasible schedule), got {solution.status}.\n{solution_snapshot(model, solution)}"

    # Compute penalty offline for the chosen solution.
    got_penalty = compute_rest_penalty_offline(
        year=year,
        month=month,
        days=days,
        doctors=doctors,
        preferences=prefs,
        assignments=solution.assignments,
    )
    got_violations = count_rest_violations_offline(
        year=year,
        month=month,
        days=days,
        doctors=doctors,
        preferences=prefs,
        assignments=solution.assignments,
    )

    # Build TWO candidate solutions manually and compare:
    # A) "Better": onsite alternates (no ons->ons), oncall fixed -> only oncall->oncall penalty
    cand_a = [
        SolverAssignment(day=1, shift_type=ShiftType.onsite, doctor_id=specialist_ids[0]),
        SolverAssignment(day=2, shift_type=ShiftType.onsite, doctor_id=specialist_ids[1]),
        SolverAssignment(day=1, shift_type=ShiftType.oncall, doctor_id=resident_id),
        SolverAssignment(day=2, shift_type=ShiftType.oncall, doctor_id=resident_id),
    ]
    cand_a_penalty = compute_rest_penalty_offline(
        year=year,
        month=month,
        days=days,
        doctors=doctors,
        preferences=prefs,
        assignments=cand_a,
    )

    # B) "Worse": same onsite doctor both days -> adds ons->ons penalty on top of oncall->oncall
    cand_b = [
        SolverAssignment(day=1, shift_type=ShiftType.onsite, doctor_id=specialist_ids[0]),
        SolverAssignment(day=2, shift_type=ShiftType.onsite, doctor_id=specialist_ids[0]),
        SolverAssignment(day=1, shift_type=ShiftType.oncall, doctor_id=resident_id),
        SolverAssignment(day=2, shift_type=ShiftType.oncall, doctor_id=resident_id),
    ]
    cand_b_penalty = compute_rest_penalty_offline(
        year=year,
        month=month,
        days=days,
        doctors=doctors,
        preferences=prefs,
        assignments=cand_b,
    )

    assert cand_a_penalty < cand_b_penalty, (
        "Test setup broken: alternating onsite should be better than repeating onsite.\n"
        f"A={cand_a_penalty} B={cand_b_penalty}"
    )

    expected_best = min(cand_a_penalty, cand_b_penalty)

    assert got_penalty == expected_best, (
        "Solver should pick a feasible solution with the lowest rest penalty among obvious candidates.\n"
        f"got_penalty={got_penalty} expected_best={expected_best}\n"
        f"got_violations={got_violations}\n"
        f"candidate_penalties: A={cand_a_penalty} B={cand_b_penalty}\n"
        f"{solution_snapshot(model, solution)}"
    )


# --------------------------------------------------------------------------------------
# 2) Offline unit-ish test: cross-shift penalty depends on doctor role
# --------------------------------------------------------------------------------------


@pytest.mark.unit
def test_cross_shift_penalty_is_higher_for_specialist_than_resident(make_preferences):
    """
    OFFLINE UNIT-ISH TEST.

    Same exact assignment pattern (cross-shift between consecutive days),
    but doctor role differs:
    - specialist cross-shift should be penalized more than resident cross-shift.
    """
    year = 2026
    month = 1
    days = [1, 2]

    # Same pattern:
    # doc does onsite on day 1, and oncall on day 2 => cross-shift (ons->oncall)
    assignments = [
        SolverAssignment(day=1, shift_type=ShiftType.onsite, doctor_id=1),
        SolverAssignment(day=2, shift_type=ShiftType.oncall, doctor_id=1),
    ]

    prefs = make_preferences(doctor_ids=[1])

    # Variant A: doctor is specialist
    doctors_a = {1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=False)}
    penalty_a = compute_rest_penalty_offline(
        year=year,
        month=month,
        days=days,
        doctors=doctors_a,
        preferences=prefs,
        assignments=assignments,
    )

    # Variant B: doctor is resident
    doctors_b = {1: DoctorInput(id=1, role=DoctorRole.resident, is_head=False)}
    penalty_b = compute_rest_penalty_offline(
        year=year,
        month=month,
        days=days,
        doctors=doctors_b,
        preferences=prefs,
        assignments=assignments,
    )

    assert penalty_a > penalty_b, (
        "Expected specialist cross-shift penalty to be higher than resident cross-shift penalty.\n"
        f"specialist_penalty={penalty_a} resident_penalty={penalty_b}"
    )


# --------------------------------------------------------------------------------------
# 3-4) Weekend exception (Sat->Sun) for cross-shift
# --------------------------------------------------------------------------------------


@pytest.mark.unit
def test_weekend_exception_true_skips_cross_penalty(make_doctors, make_preferences):
    """
    OFFLINE UNIT-ISH TEST.

    Weekend exception applies only for Sat->Sun and only for cross-shift patterns.
    Here we build Sat->Sun cross-shift and set allow_weekend_consecutive_onsite_oncall=True.
    Expect: cross penalty is 0 for that pair (and cross violations count is 0).
    """
    # Concrete weekend pair:
    # 2026-01-03 is Saturday, 2026-01-04 is Sunday.
    year = 2026
    month = 1
    d_sat = 3
    d_sun = 4

    assert datetime(year, month, d_sat).weekday() == 5, "Sanity check failed: expected Saturday (weekday=5)."
    assert datetime(year, month, d_sun).weekday() == 6, "Sanity check failed: expected Sunday (weekday=6)."

    days = [d_sat, d_sun]

    doctors = make_doctors(num_specialists=1, num_residents=0, include_head=False, start_id=1)
    doc_id = list(doctors.keys())[0]

    prefs = make_preferences(
        doctors=doctors,
        allow_weekend_consecutive_by_doc={doc_id: True},
    )

    # Cross-shift Sat->Sun for the same doctor:
    assignments = [
        SolverAssignment(day=d_sat, shift_type=ShiftType.onsite, doctor_id=doc_id),
        SolverAssignment(day=d_sun, shift_type=ShiftType.oncall, doctor_id=doc_id),
    ]

    violations = count_rest_violations_offline(
        year=year,
        month=month,
        days=days,
        doctors=doctors,
        preferences=prefs,
        assignments=assignments,
    )
    penalty = compute_rest_penalty_offline(
        year=year,
        month=month,
        days=days,
        doctors=doctors,
        preferences=prefs,
        assignments=assignments,
    )

    assert (
        violations["cross"] == 0
    ), f"Expected no cross violations due to weekend exception. got violations={violations}"
    assert penalty == 0, f"Expected zero penalty for Sat->Sun cross-shift with exception enabled. got penalty={penalty}"


@pytest.mark.unit
def test_weekend_exception_false_applies_cross_penalty(make_doctors, make_preferences):
    """
    OFFLINE UNIT-ISH TEST.

    Same Sat->Sun cross-shift pattern as above, but allow_weekend_consecutive_onsite_oncall=False.
    Expect: cross violations > 0 and penalty > 0.
    """
    year = 2026
    month = 1
    d_sat = 3
    d_sun = 4

    assert datetime(year, month, d_sat).weekday() == 5, "Sanity check failed: expected Saturday (weekday=5)."
    assert datetime(year, month, d_sun).weekday() == 6, "Sanity check failed: expected Sunday (weekday=6)."

    days = [d_sat, d_sun]

    doctors = make_doctors(num_specialists=1, num_residents=0, include_head=False, start_id=1)
    doc_id = list(doctors.keys())[0]

    prefs = make_preferences(
        doctors=doctors,
        allow_weekend_consecutive_by_doc={doc_id: False},
    )

    assignments = [
        SolverAssignment(day=d_sat, shift_type=ShiftType.onsite, doctor_id=doc_id),
        SolverAssignment(day=d_sun, shift_type=ShiftType.oncall, doctor_id=doc_id),
    ]

    violations = count_rest_violations_offline(
        year=year,
        month=month,
        days=days,
        doctors=doctors,
        preferences=prefs,
        assignments=assignments,
    )
    penalty = compute_rest_penalty_offline(
        year=year,
        month=month,
        days=days,
        doctors=doctors,
        preferences=prefs,
        assignments=assignments,
    )

    assert violations["cross"] > 0, f"Expected cross violations when exception is disabled. got violations={violations}"
    assert penalty > 0, f"Expected positive penalty when exception is disabled. got penalty={penalty}"


# --------------------------------------------------------------------------------------
# 5) Defensive / regression tests: objective builder should not crash when x is missing
# --------------------------------------------------------------------------------------


def test_objective_builder_is_defensive_when_x_missing_in_inactive_days(
    make_hard_model, make_doctors, make_preferences
):
    """
    REGRESSION / DEFENSIVE INTEGRATION TEST.

    We build a model where:
    - model.days has two consecutive days [1, 2] (objective loops over day pairs),
    - day 2 is ignored (so active_days == [1]),
    - allowed_slots exist only for day 1 (so x has NO vars for day 2).

    The objective must skip missing x vars safely (no crash).

    Expect:
    - engine returns OK (hard constraints are feasible for active day 1),
    - no crash.
    """
    year = 2026
    month = 1

    doctors = make_doctors(num_specialists=1, num_residents=1, include_head=False, start_id=1)
    prefs = make_preferences(doctors=doctors)

    # Ignoring a whole day is represented by ignoring BOTH slots.
    ignore_slots = {(2, ShiftType.onsite), (2, ShiftType.oncall)}

    # Only day 1 has allowed slots; day 2 is ignored and has no x vars.
    allowed_slots = {
        (1, ShiftType.onsite): [1],  # specialist
        (1, ShiftType.oncall): [2],  # resident
    }

    model = make_hard_model(
        year=year,
        month=month,
        days=[1, 2],
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_slots=ignore_slots,
        active_days=[1],
        allowed_slots=allowed_slots,
    )

    solution = engine.build_and_solve(model)
    assert solution.status == SolverStatus.OK, (
        "Expected OK (objective must not crash even if some x vars are missing).\n"
        f"{solution_snapshot(model, solution)}"
    )


@pytest.mark.unit
def test_objective_builder_returns_zero_var_when_participants_empty(
    make_hard_model, make_doctors, make_preferences, make_problem_data
):
    """
    REGRESSION UNIT-ISH TEST (direct objective_builder call).

    Edge case:
    - participant_doctor_ids is empty => the loop over doctors does not run,
      so objective_builder must still return a valid IntVar (0 penalty), not crash.

    We do NOT use engine here on purpose.
    """
    doctors = make_doctors(num_specialists=1, num_residents=1, include_head=False, start_id=1)
    prefs = make_preferences(doctors=doctors)

    model = make_hard_model(
        year=2026,
        month=1,
        days=[1, 2],
        active_days=[1, 2],
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(),  # the key edge-case
        ignore_slots=set(),
        allowed_slots={
            (1, ShiftType.onsite): [1],
            (1, ShiftType.oncall): [2],
            (2, ShiftType.onsite): [1],
            (2, ShiftType.oncall): [2],
        },
    )

    # Build a minimal CP-SAT model and x dict.
    cp = cp_model.CpModel()
    x: dict[tuple[int, ShiftType, int], cp_model.IntVar] = {}

    problem = make_problem_data(
        year=model.year,
        month=model.month,
        days=list(model.days),
        doctors=dict(model.doctors),
        preferences=dict(model.preferences),
        participant_doctor_ids=set(model.participant_doctor_ids),
        ignore_slots=set(model.ignore_slots),
    )

    total_penalty = objective_builder.attach_rest_objective(cp=cp, x=x, model=model, problem=problem)

    assert total_penalty is not None, "Expected objective_builder to return a valid IntVar, got None."
    assert isinstance(total_penalty, cp_model.IntVar), f"Expected IntVar, got {type(total_penalty)}."
