# tests/solver/test_cross_month_rest.py
from __future__ import annotations

from typing import Dict, List, Tuple

from ortools.sat.python import cp_model

from backend.core.diagnostics import compute_quality
from backend.core.objective_builder import attach_rest_objective
from backend.core.types import DoctorCarryover, EdgeAssignment, MonthCarryover
from backend.models.common_enums import ShiftType


def _payload(*, participant_ids: List[int], assignments: List[dict]) -> dict:
    """
    Minimal payload builder for diagnostics tests.

    NOTE:
    - inputs_snapshot must exist (contract requirement),
    - doctors snapshot keys are strings (JSON style).
    """
    doctors_snapshot = {
        str(did): {
            "display_name": f"Doctor {did}",
            "role": "resident",
            "is_head": False,
            "is_active_at_snapshot": True,
        }
        for did in participant_ids
    }
    return {
        "participant_doctor_ids": list(participant_ids),
        "assignments": list(assignments),
        "inputs_snapshot": {"doctors": doctors_snapshot, "preference_version_id_by_doctor": {}},
        "meta": {"labels": [], "exceptions": []},
    }


def test_diagnostics_cross_month_rest_counts_violation(make_problem_data):
    """
    Cross-month rest violation must be counted in diagnostics:

    Example:
    - previous month last day: onsite
    - current month day 1: onsite
    => onsite->onsite consecutive violation on the boundary.

    We assert:
    - summary.rest_violations == 1
    - findings contain rest_consecutive_violation with cross_month=True and day==1
    """
    # Build carryover: previous month has day 31 onsite for doctor 1
    carryover = MonthCarryover(
        prev_year=2026,
        prev_month=1,
        per_doctor={
            1: DoctorCarryover(
                edge_assignments_last=[
                    EdgeAssignment(day=31, shift_type=ShiftType.onsite, doctor_id=1),
                ]
            )
        },
    )

    # Build ProblemData for Feb 2026 with days [1, 2]
    # Preferences are created by fixture; allow_weekend_consecutive defaults False.
    problem = make_problem_data(
        year=2026,
        month=2,
        days=[1, 2],
        participant_doctor_ids={1},
        carryover=carryover,
    )

    # Current month schedule assigns doctor 1 onsite on day 1
    payload = _payload(
        participant_ids=[1],
        assignments=[
            {"day": 1, "shift_type": "onsite", "doctor_id": 1},
        ],
    )

    out = compute_quality(problem=problem, payload=payload)

    # 1) Summary should count it
    assert int(out["summary"]["rest_violations"]) == 1

    # 2) Findings should include a cross-month rest violation
    findings = out["details"]["findings"]
    rest = [
        f
        for f in findings
        if f.get("code") == "rest_consecutive_violation" and f.get("context", {}).get("cross_month") is True
    ]
    assert len(rest) == 1
    assert int(rest[0]["context"]["day"]) == 1


def test_diagnostics_cross_month_weekend_exception_skips_cross(make_problem_data, make_preferences):
    """
    Weekend exception rule:
    Sat->Sun cross-shift is NOT penalized if allow_weekend_consecutive_onsite_oncall=True.

    We choose a real calendar boundary where:
    - 2026-02-28 is Saturday
    - 2026-03-01 is Sunday

    Scenario:
    - prev day (Feb 28): onsite
    - current day1 (Mar 1): oncall
    With allow_weekend_consecutive=True => NO rest violation.
    """
    carryover = MonthCarryover(
        prev_year=2026,
        prev_month=2,
        per_doctor={
            1: DoctorCarryover(
                edge_assignments_last=[
                    EdgeAssignment(day=28, shift_type=ShiftType.onsite, doctor_id=1),
                ]
            )
        },
    )

    # Build preferences with weekend exception enabled for doc 1
    prefs = make_preferences(doctor_ids=[1], allow_weekend_consecutive_by_doc={1: True})

    problem = make_problem_data(
        year=2026,
        month=3,
        days=[1, 2],
        participant_doctor_ids={1},
        preferences=prefs,
        carryover=carryover,
    )

    payload = _payload(
        participant_ids=[1],
        assignments=[
            {"day": 1, "shift_type": "oncall", "doctor_id": 1},
        ],
    )

    out = compute_quality(problem=problem, payload=payload)
    assert int(out["summary"]["rest_violations"]) == 0


def test_solver_objective_contains_cross_month_rest_term(make_hard_model, make_problem_data):
    """
    This test verifies SOLVER side (objective terms), not diagnostics.

    We build a tiny CP-SAT model:
    - one doctor
    - day 1 onsite variable exists and is forced to 1
    - carryover says doctor worked onsite on prev month last day
    => attach_rest_objective must add a penalty term.

    We solve and expect objective == REST_ONS_ONS_WEIGHT.
    """
    # Carryover: prev month day 31 onsite
    carryover = MonthCarryover(
        prev_year=2026,
        prev_month=1,
        per_doctor={
            1: DoctorCarryover(
                edge_assignments_last=[
                    EdgeAssignment(day=31, shift_type=ShiftType.onsite, doctor_id=1),
                ]
            )
        },
    )

    # Build HardModel and ProblemData consistently via fixture
    # We force allowed_slots so day 1 onsite var definitely exists.
    allowed_slots = {(1, ShiftType.onsite): [1], (1, ShiftType.oncall): [1]}
    model = make_hard_model(
        year=2026,
        month=2,
        days=[1],
        participant_doctor_ids={1},
        allowed_slots=allowed_slots,
        carryover=carryover,
    )

    # Build real ProblemData (Pylance-friendly) for attach_rest_objective(...)
    problem = make_problem_data(
        year=2026,
        month=2,
        days=[1],
        participant_doctor_ids={1},
        allowed_slots=allowed_slots,
        carryover=carryover,
    )

    cp = cp_model.CpModel()

    # Decision vars: only day 1 onsite is relevant for this test
    x: Dict[Tuple[int, ShiftType, int], cp_model.IntVar] = {}
    x[(1, ShiftType.onsite, 1)] = cp.NewBoolVar("x_d1_ons_doc1")
    x[(1, ShiftType.oncall, 1)] = cp.NewBoolVar("x_d1_oncall_doc1")

    # Force: onsite on day 1 is chosen, oncall is not
    cp.Add(x[(1, ShiftType.onsite, 1)] == 1)
    cp.Add(x[(1, ShiftType.oncall, 1)] == 0)

    total_penalty = attach_rest_objective(cp=cp, x=x, model=model, problem=problem)

    # Minimize and solve
    cp.Minimize(total_penalty)
    solver = cp_model.CpSolver()
    status = solver.Solve(cp)

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    # REST_ONS_ONS_WEIGHT is in scoring.py; attach_rest_objective uses it directly
    # We assert penalty == 1 * weight
    from backend.core import scoring  # local import to keep test module clean

    assert int(solver.Value(total_penalty)) == int(scoring.REST_ONS_ONS_WEIGHT)
