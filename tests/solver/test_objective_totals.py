# tests/solver/test_objective_totals.py
"""
Soft-objective tests for ETAP 3B totals:
- monthly totals: max_* and target_*
- weekend totals: max_*_weekends and target_*_weekends

Important behavior:
- Both max and target penalties should be escalating (quadratic): deviation^2 / excess^2.
  This encourages spreading unavoidable violations across doctors instead of concentrating them.

Design notes:
- We use non-consecutive days so rest rules do not influence the choice.
- Oncall is fixed to a resident to remove oncall choices.

IMPORTANT:
- For readable failure messages we use solution_snapshot(model, solution).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from ortools.sat.python import cp_model

from backend.core import engine, objective_builder
from backend.core.types import SolverStatus
from backend.models.common_enums import ShiftType

from ._helpers import solution_snapshot

pytestmark = [pytest.mark.solver]


def _count_assignments(solution, *, doctor_id: int, shift_type: ShiftType) -> int:
    """Count how many assignments a doctor has for a given shift type."""
    return sum(1 for a in solution.assignments if a.doctor_id == doctor_id and a.shift_type == shift_type)


def _get_assigned_doctor(solution, *, day: int, shift_type: ShiftType) -> int | None:
    """Return doctor_id assigned to (day, shift_type), or None if not present."""
    for a in solution.assignments:
        if a.day == day and a.shift_type == shift_type:
            return a.doctor_id
    return None


def test_solver_avoids_exceeding_max_onsite_total_when_possible(make_hard_model, make_doctors, make_preferences):
    """
    Integration test (basic max behavior).

    days [1, 3] => not consecutive => rest rules do nothing.
    Two specialists can do onsite on both days.
    Doc A has max_onsite_total=1, doc B has no max.

    Expect:
    - solver does NOT assign doc A onsite twice if it can avoid it.
    """
    year = 2026
    month = 1
    days = [1, 3]

    doctors = make_doctors(num_specialists=2, num_residents=1, include_head=False, start_id=1)
    specialist_ids = [doc_id for doc_id, d in doctors.items() if d.role.value == "specialist"]
    resident_id = [doc_id for doc_id, d in doctors.items() if d.role.value == "resident"][0]

    prefs = make_preferences(doctors=doctors)

    doc_a = specialist_ids[0]
    doc_b = specialist_ids[1]

    prefs[doc_a].max_onsite_total = 1

    allowed_slots = {
        (1, ShiftType.onsite): [doc_a, doc_b],
        (3, ShiftType.onsite): [doc_a, doc_b],
        (1, ShiftType.oncall): [resident_id],
        (3, ShiftType.oncall): [resident_id],
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
    assert solution.status == SolverStatus.OK, f"Expected OK.\n{solution_snapshot(model, solution)}"

    a_onsite = _count_assignments(solution, doctor_id=doc_a, shift_type=ShiftType.onsite)
    assert a_onsite <= 1, (
        "Expected solver to avoid violating max_onsite_total when it can.\n"
        f"doc_a={doc_a} a_onsite={a_onsite}\n"
        f"{solution_snapshot(model, solution)}"
    )


def test_quadratic_max_penalty_prefers_spreading_excess(make_hard_model, make_doctors, make_preferences):
    """
    Integration test: quadratic (escalating) MAX penalty.

    We force unavoidable max violations:
    - 6 non-consecutive days (no rest objective influence)
    - 2 specialists cover onsite, 1 resident fixed oncall
    - both specialists have max_onsite_total = 2
    - total onsite assignments = 6 => we MUST exceed max (total capacity 4)

    Two key distributions have the same linear total excess:
    A) Concentrated: (4,2) => excess (2,0) => linear sum=2, quadratic sum=4
    B) Spread:       (3,3) => excess (1,1) => linear sum=2, quadratic sum=2 (better)

    Expect:
    - solver chooses (3,3), i.e. spreads max excess across both doctors.
    """
    year = 2026
    month = 1
    days = [1, 3, 5, 7, 9, 11]  # non-consecutive => rest rules do nothing

    doctors = make_doctors(num_specialists=2, num_residents=1, include_head=False, start_id=1)
    specialist_ids = [doc_id for doc_id, d in doctors.items() if d.role.value == "specialist"]
    resident_id = [doc_id for doc_id, d in doctors.items() if d.role.value == "resident"][0]

    doc_a, doc_b = specialist_ids[0], specialist_ids[1]

    prefs = make_preferences(doctors=doctors)
    prefs[doc_a].max_onsite_total = 2
    prefs[doc_b].max_onsite_total = 2

    allowed_slots: dict[tuple[int, ShiftType], list[int]] = {}
    for d in days:
        allowed_slots[(d, ShiftType.onsite)] = [doc_a, doc_b]
        allowed_slots[(d, ShiftType.oncall)] = [resident_id]

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
    assert solution.status == SolverStatus.OK, f"Expected OK.\n{solution_snapshot(model, solution)}"

    a_onsite = _count_assignments(solution, doctor_id=doc_a, shift_type=ShiftType.onsite)
    b_onsite = _count_assignments(solution, doctor_id=doc_b, shift_type=ShiftType.onsite)

    assert (a_onsite, b_onsite) == (3, 3), (
        "Expected solver to spread max violations because quadratic excess penalty "
        "makes concentration more expensive.\n"
        f"got (a,b)=({a_onsite},{b_onsite})\n"
        f"{solution_snapshot(model, solution)}"
    )


def test_quadratic_target_penalty_prefers_spreading_deviation(make_hard_model, make_doctors, make_preferences):
    """
    Integration test: quadratic (escalating) TARGET penalty.

    Setup:
    - 2 non-consecutive days [1, 3] (no rest influence)
    - 2 specialists can cover onsite
    - 1 resident fixed oncall
    - both specialists have target_onsite_total = 0 (they prefer no onsite shifts)

    Two relevant feasible patterns for onsite:
    A) Spread: doc1=1, doc2=1 => deviations (1,1) => linear=2, quadratic=2 (better)
    B) Concentrate: doc1=2, doc2=0 => deviations (2,0) => linear=2 (tie), quadratic=4 (worse)

    Expect:
    - solver chooses spread (two different doctors doing onsite).
    """
    year = 2026
    month = 1
    days = [1, 3]

    doctors = make_doctors(num_specialists=2, num_residents=1, include_head=False, start_id=1)
    specialist_ids = [doc_id for doc_id, d in doctors.items() if d.role.value == "specialist"]
    resident_id = [doc_id for doc_id, d in doctors.items() if d.role.value == "resident"][0]

    prefs = make_preferences(doctors=doctors)

    for sid in specialist_ids:
        prefs[sid].target_onsite_total = 0

    allowed_slots = {
        (1, ShiftType.onsite): list(specialist_ids),
        (3, ShiftType.onsite): list(specialist_ids),
        (1, ShiftType.oncall): [resident_id],
        (3, ShiftType.oncall): [resident_id],
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
    assert solution.status == SolverStatus.OK, f"Expected OK.\n{solution_snapshot(model, solution)}"

    d1 = _get_assigned_doctor(solution, day=1, shift_type=ShiftType.onsite)
    d3 = _get_assigned_doctor(solution, day=3, shift_type=ShiftType.onsite)

    assert d1 is not None and d3 is not None
    assert d1 != d3, (
        "Expected solver to spread onsite assignments across two specialists "
        "because quadratic target penalty makes concentration more expensive.\n"
        f"day1={d1} day3={d3}\n"
        f"{solution_snapshot(model, solution)}"
    )


def test_solver_avoids_weekend_onsite_when_max_weekends_zero(make_hard_model, make_doctors, make_preferences):
    """
    Integration test (weekend max).

    One weekend day to avoid rest penalties completely.
    2026-01-03 is Saturday.

    Two specialists can do onsite. Doc A has max_onsite_weekends=0.
    Expect:
    - solver assigns onsite to doc B if possible.
    """
    year = 2026
    month = 1
    d_sat = 3

    assert datetime(year, month, d_sat).weekday() == 5, "Sanity check failed: expected Saturday (weekday=5)."

    days = [d_sat]

    doctors = make_doctors(num_specialists=2, num_residents=1, include_head=False, start_id=1)
    specialist_ids = [doc_id for doc_id, d in doctors.items() if d.role.value == "specialist"]
    resident_id = [doc_id for doc_id, d in doctors.items() if d.role.value == "resident"][0]

    doc_a = specialist_ids[0]
    doc_b = specialist_ids[1]

    prefs = make_preferences(doctors=doctors)
    prefs[doc_a].max_onsite_weekends = 0

    allowed_slots = {
        (d_sat, ShiftType.onsite): [doc_a, doc_b],
        (d_sat, ShiftType.oncall): [resident_id],
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
    assert solution.status == SolverStatus.OK, f"Expected OK.\n{solution_snapshot(model, solution)}"

    got_onsite = _get_assigned_doctor(solution, day=d_sat, shift_type=ShiftType.onsite)
    assert got_onsite == doc_b, (
        "Expected solver to avoid assigning doc A onsite on a weekend when max_onsite_weekends=0.\n"
        f"got_onsite={got_onsite} doc_a={doc_a} doc_b={doc_b}\n"
        f"{solution_snapshot(model, solution)}"
    )


def test_totals_objective_is_defensive_when_x_missing_in_ignored_day(make_hard_model, make_doctors, make_preferences):
    """
    Defensive integration test.

    model.days includes [1, 2]
    day 2 is ignored => active_days == [1]
    allowed_slots exist only for day 1 => x has NO vars for day 2

    Expect:
    - engine returns OK (no crash).
    """
    doctors = make_doctors(num_specialists=1, num_residents=1, include_head=False, start_id=1)
    prefs = make_preferences(doctors=doctors)

    # Ignoring a whole day is now represented by ignoring BOTH slots.
    ignore_slots = {(2, ShiftType.onsite), (2, ShiftType.oncall)}

    allowed_slots = {
        (1, ShiftType.onsite): [1],
        (1, ShiftType.oncall): [2],
    }

    model = make_hard_model(
        year=2026,
        month=1,
        days=[1, 2],
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_slots=ignore_slots,
        active_days=[1],
        allowed_slots=allowed_slots,
    )

    solution = engine.build_and_solve(model)
    assert solution.status == SolverStatus.OK, f"Expected OK (no crash).\n{solution_snapshot(model, solution)}"


@pytest.mark.unit
def test_totals_objective_returns_zero_var_when_participants_empty(
    make_hard_model, make_doctors, make_preferences, make_problem_data
):
    """
    Unit-ish test (direct objective_builder call).

    If participant_doctor_ids is empty, totals objective should return a valid 0 IntVar.
    """
    doctors = make_doctors(num_specialists=1, num_residents=1, include_head=False, start_id=1)
    prefs = make_preferences(doctors=doctors)

    model = make_hard_model(
        year=2026,
        month=1,
        days=[1],
        active_days=[1],
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(),  # key edge-case
        ignore_slots=set(),
        allowed_slots={
            (1, ShiftType.onsite): [1],
            (1, ShiftType.oncall): [2],
        },
    )

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

    v_tot = objective_builder.attach_totals_objective(cp=cp, x=x, model=model, problem=problem)

    assert isinstance(v_tot, cp_model.IntVar)
    assert v_tot.Proto().domain == [0, 0]
