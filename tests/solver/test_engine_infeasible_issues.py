# tests/solver/test_engine_infeasible_issues.py
"""
Tests for "post-solve infeasible explanation" in backend.core.engine.

Goal:
- When CP-SAT returns INFEASIBLE, engine should attach user-friendly issues:
  - per-day when we can derive a clear reason from HardModel
  - otherwise a global fallback day=0 (cp_infeasible)

We test deterministic reasons derived from HardModel:
- missing candidates for a required slot -> no_*_candidate
- missing specialist among required shifts -> no_specialist
- forced double shift on the same day (only one candidate can cover both required roles)
  -> forced_double_shift_same_day
  (single_candidate_for_both_roles may be omitted to avoid redundancy)
- fallback cp_infeasible when no per-day reasons can be derived
"""

from __future__ import annotations

import pytest

from backend.core import engine
from backend.core.issues import (
    CP_INFEASIBLE,
    FORCED_DOUBLE_SHIFT_SAME_DAY,
    NO_ONCALL_CANDIDATE,
    NO_ONSITE_CANDIDATE,
    NO_SPECIALIST,
)
from backend.core.types import DoctorInput, SolverStatus
from backend.models.common_enums import DoctorRole, ShiftType

pytestmark = [pytest.mark.solver]


def _issues_by_day(solution) -> dict[int, list[str]]:
    """
    Helper: group issue codes by day for easy assertions.

    Returns:
        { day_int: [code1, code2, ...] }
    """
    out: dict[int, list[str]] = {}
    for i in solution.issues or []:
        out.setdefault(int(i.day), []).append(i.code)
    return out


def test_engine_infeasible_includes_no_onsite_candidate_issue(make_hard_model, make_preferences):
    """
    If a required slot has no candidates, CP becomes infeasible.
    Engine should return INFEASIBLE and include NO_ONSITE_CANDIDATE for that day.
    """
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=False),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
    }
    preferences = make_preferences(doctors=doctors)

    model = make_hard_model(
        days=[1],
        doctors=doctors,
        preferences=preferences,
        participant_doctor_ids=set(doctors.keys()),
        ignore_days=set(),
        ignore_slots=set(),
        # Keep the key with an empty list on purpose: this is a "required but impossible" slot.
        allowed_slots={
            (1, ShiftType.onsite): [],
            (1, ShiftType.oncall): [1, 2],
        },
    )

    solution = engine.build_and_solve(model)

    assert solution.status == SolverStatus.INFEASIBLE
    by_day = _issues_by_day(solution)
    assert NO_ONSITE_CANDIDATE in by_day.get(1, [])
    # Oncall has candidates, so we should NOT claim "no_oncall_candidate".
    assert NO_ONCALL_CANDIDATE not in by_day.get(1, [])


def test_engine_infeasible_includes_no_specialist_issue(make_hard_model, make_preferences):
    """
    If a day requires at least one specialist, but only residents are available,
    CP becomes infeasible. Engine should attach NO_SPECIALIST for that day.
    """
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.resident, is_head=False),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
    }
    preferences = make_preferences(doctors=doctors)

    model = make_hard_model(
        days=[1],
        doctors=doctors,
        preferences=preferences,
        participant_doctor_ids=set(doctors.keys()),
        ignore_days=set(),
        ignore_slots=set(),
        allowed_slots={
            (1, ShiftType.onsite): [1, 2],
            (1, ShiftType.oncall): [1, 2],
        },
    )

    solution = engine.build_and_solve(model)

    assert solution.status == SolverStatus.INFEASIBLE
    by_day = _issues_by_day(solution)
    assert NO_SPECIALIST in by_day.get(1, [])
    # Candidates exist for both shifts, so we should not emit "no_*_candidate".
    assert NO_ONSITE_CANDIDATE not in by_day.get(1, [])
    assert NO_ONCALL_CANDIDATE not in by_day.get(1, [])


def test_engine_infeasible_includes_forced_double_shift_issue(make_hard_model, make_preferences):
    """
    If onsite and oncall are both required, but there is only ONE doctor available for BOTH,
    coverage forces the same doctor into both shifts, but "double shift same day" is forbidden.

    Engine should include FORCED_DOUBLE_SHIFT_SAME_DAY for that day.

    Note:
    - SINGLE_CANDIDATE_FOR_BOTH_ROLES is a more general description of the same situation.
      Engine may omit it to avoid redundant messages.
    """
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=False),
    }
    preferences = make_preferences(doctors=doctors)

    model = make_hard_model(
        days=[1],
        doctors=doctors,
        preferences=preferences,
        participant_doctor_ids=set(doctors.keys()),
        ignore_days=set(),
        ignore_slots=set(),
        allowed_slots={
            (1, ShiftType.onsite): [1],
            (1, ShiftType.oncall): [1],
        },
    )

    solution = engine.build_and_solve(model)

    assert solution.status == SolverStatus.INFEASIBLE
    by_day = _issues_by_day(solution)

    assert FORCED_DOUBLE_SHIFT_SAME_DAY in by_day.get(1, [])

    # Optional / may be omitted as redundant:
    # If engine includes it, cool; if not, this test should still pass.
    # So we do NOT assert on SINGLE_CANDIDATE_FOR_BOTH_ROLES here.
    assert NO_SPECIALIST not in by_day.get(1, [])


def test_engine_derive_fallback_cp_infeasible_when_no_day_reasons(make_hard_model, make_preferences):
    """
    Safety-net test: _derive_infeasible_issues should return a global fallback
    issue (day=0, code=CP_INFEASIBLE) if it cannot derive any day-level reason.

    This test validates the helper behavior directly.
    """
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=False),
        2: DoctorInput(id=2, role=DoctorRole.specialist, is_head=False),
    }
    preferences = make_preferences(doctors=doctors)

    model = make_hard_model(
        days=[1],
        doctors=doctors,
        preferences=preferences,
        participant_doctor_ids=set(doctors.keys()),
        ignore_days=set(),
        ignore_slots=set(),
        allowed_slots={
            (1, ShiftType.onsite): [1, 2],
            (1, ShiftType.oncall): [1, 2],
        },
    )

    derived = engine._derive_infeasible_issues(model)  # intentional: private helper unit test

    assert len(derived) == 1
    assert int(derived[0].day) == 0
    assert derived[0].code == CP_INFEASIBLE


def test_engine_infeasible_always_includes_at_least_one_issue(make_hard_model, make_preferences):
    """
    Guarantee for FE:
    - If engine returns INFEASIBLE, it MUST also return at least one issue.
    This makes sure UI always has something meaningful to show the user.
    """
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=False),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
    }
    preferences = make_preferences(doctors=doctors)

    # Make the model infeasible in a simple deterministic way:
    # required onsite has no candidates.
    model = make_hard_model(
        days=[1],
        doctors=doctors,
        preferences=preferences,
        participant_doctor_ids=set(doctors.keys()),
        ignore_days=set(),
        ignore_slots=set(),
        allowed_slots={
            (1, ShiftType.onsite): [],
            (1, ShiftType.oncall): [1, 2],
        },
    )

    solution = engine.build_and_solve(model)

    assert solution.status == SolverStatus.INFEASIBLE
    assert solution.issues is not None
    assert len(solution.issues) >= 1


def test_engine_empty_does_not_include_issues(make_hard_model, make_preferences):
    """
    Guarantee for FE:
    - If engine returns EMPTY (no allowed slots at all), it should NOT attach issues.
      This is not an "infeasible schedule", it's "nothing to solve".
    """
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=False),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
    }
    preferences = make_preferences(doctors=doctors)

    # EMPTY happens when allowed_slots dict is empty.
    model = make_hard_model(
        days=[1],
        doctors=doctors,
        preferences=preferences,
        participant_doctor_ids=set(doctors.keys()),
        ignore_days=set(),
        ignore_slots=set(),
        allowed_slots={},  # <- key part
    )

    solution = engine.build_and_solve(model)

    assert solution.status == SolverStatus.EMPTY
    # For EMPTY we do not want "fake" issues.
    assert solution.issues is None or len(solution.issues) == 0


def test_engine_not_solved_does_not_include_issues(monkeypatch, make_hard_model, make_preferences):
    """
    Guarantee for FE:
    - If engine returns NOT_SOLVED (e.g. solver status UNKNOWN / MODEL_INVALID),
      it should NOT attach "infeasible explanation" issues.
      We only attach issues for INFEASIBLE because only that path is deterministic here.

    We force NOT_SOLVED by monkeypatching CpSolver.Solve to return cp_model.UNKNOWN.
    """
    from ortools.sat.python import cp_model

    # Patch CpSolver.Solve to always return UNKNOWN.
    original_solve = cp_model.CpSolver.Solve

    def _fake_solve(self, model):  # same signature as OR-Tools
        return cp_model.UNKNOWN

    monkeypatch.setattr(cp_model.CpSolver, "Solve", _fake_solve)

    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=False),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
    }
    preferences = make_preferences(doctors=doctors)

    model = make_hard_model(
        days=[1],
        doctors=doctors,
        preferences=preferences,
        participant_doctor_ids=set(doctors.keys()),
        ignore_days=set(),
        ignore_slots=set(),
        allowed_slots={
            (1, ShiftType.onsite): [1, 2],
            (1, ShiftType.oncall): [1, 2],
        },
    )

    solution = engine.build_and_solve(model)

    assert solution.status == SolverStatus.NOT_SOLVED
    assert solution.issues is None or len(solution.issues) == 0

    # (Optional safety) restore original Solve if you ever run into weirdness in the future.
    monkeypatch.setattr(cp_model.CpSolver, "Solve", original_solve)
