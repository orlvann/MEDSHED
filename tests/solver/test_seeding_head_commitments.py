# tests/solver/test_seeding_head_commitments.py
"""
Tests for "Head commitments" (must-have head preferred slots).

IMPORTANT (current architecture):
- Head commitments validation runs in: backend/core/scheduler.py (generate_schedule),
  after HardModel is built by backend/core/constraint_builder.py.
- Engine (backend/core/engine.py) focuses on CP-SAT model building + solving.

Rule summary:

* If head preferred slot is ignored -> INFEASIBLE + issue
* If head preferred slot is not allowed (head not in allowed_slots for that slot) -> INFEASIBLE + issue
* If multiple heads prefer the same slot -> INFEASIBLE + issue
* If the same head prefers onsite and oncall on the same day -> INFEASIBLE + issue

We test this through scheduler.generate_schedule(), because scheduler owns:
- feasibility pre-check (backend/core/feasibility.py),
- HardModel build (backend/core/constraint_builder.py),
- head commitments validation (backend/core/seeding.py -> validate_head_commitments),
- calling the solver engine (backend/core/engine.py).
"""

from __future__ import annotations

import pytest

from backend.core import scheduler
from backend.core.issues import (
    HEAD_COMMITMENT_CONFLICT,
    HEAD_COMMITMENT_DOUBLE_SHIFT_SAME_DAY,
    HEAD_COMMITMENT_IGNORED_SLOT,
    HEAD_COMMITMENT_NOT_ALLOWED,
)
from backend.core.types import DoctorInput, SolverStatus
from backend.models.common_enums import DoctorRole, ShiftType

pytestmark = [pytest.mark.solver]


def _issue_codes(solution) -> list[str]:
    """Helper: extract issue codes from solution (safe when issues is None)."""
    return [i.code for i in (solution.issues or [])]


def _build_problem_data(
    *,
    make_problem_data,
    make_preferences,
    doctors: dict[int, DoctorInput],
    preferences_overrides: dict[int, dict],
    ignore_slots: set[tuple[int, ShiftType]] | None = None,
    unavailable_onsite_by_doc: dict[int, list[int]] | None = None,
    unavailable_oncall_by_doc: dict[int, list[int]] | None = None,
):
    """
    Build a tiny ProblemData for scheduler.generate_schedule() tests.

    Why ProblemData:
    - scheduler.generate_schedule() starts from ProblemData,
      then builds HardModel via constraint_builder.build_hard_model().

    How we simulate "head not allowed":
    - We DO NOT pass allowed_slots directly (that is HardModel-level).
    - Instead, we mark the head as unavailable for that slot via preferences
      so constraint_builder excludes the head from allowed_slots.
    """
    # 1) Start from defaults (all available) and optionally apply unavailability maps.
    preferences = make_preferences(
        doctors=doctors,
        unavailable_onsite_by_doc=unavailable_onsite_by_doc or {},
        unavailable_oncall_by_doc=unavailable_oncall_by_doc or {},
    )

    # 2) Apply overrides in a safe, explicit way (preferred days, etc.).
    for doc_id, overrides in preferences_overrides.items():
        pref = preferences[doc_id]
        for field_name, value in overrides.items():
            setattr(pref, field_name, value)

    # 3) Build ProblemData (single-day model).
    problem = make_problem_data(
        days=[1],
        doctors=doctors,
        preferences=preferences,
        participant_doctor_ids=set(doctors.keys()),
        ignore_slots=set(ignore_slots or set()),
    )
    return problem


def test_infeasible_when_two_heads_commit_same_slot(make_problem_data, make_preferences):
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=True),
        2: DoctorInput(id=2, role=DoctorRole.specialist, is_head=True),
        3: DoctorInput(id=3, role=DoctorRole.resident, is_head=False),
    }

    problem = _build_problem_data(
        make_problem_data=make_problem_data,
        make_preferences=make_preferences,
        doctors=doctors,
        preferences_overrides={
            1: {"preferred_onsite_days": [1]},
            2: {"preferred_onsite_days": [1]},
        },
    )

    result = scheduler.generate_schedule(problem)
    solution = result.solution

    assert solution.status == SolverStatus.INFEASIBLE
    assert HEAD_COMMITMENT_CONFLICT in _issue_codes(solution)
    assert result.assignments == []


def test_infeasible_when_head_commitment_targets_ignored_slot(make_problem_data, make_preferences):
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=True),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
    }

    problem = _build_problem_data(
        make_problem_data=make_problem_data,
        make_preferences=make_preferences,
        doctors=doctors,
        preferences_overrides={
            1: {"preferred_onsite_days": [1]},
        },
        ignore_slots={(1, ShiftType.onsite)},
    )

    result = scheduler.generate_schedule(problem)
    solution = result.solution

    assert solution.status == SolverStatus.INFEASIBLE
    assert HEAD_COMMITMENT_IGNORED_SLOT in _issue_codes(solution)
    assert result.assignments == []


def test_infeasible_when_head_commitment_is_not_allowed(make_problem_data, make_preferences):
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=True),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
    }

    # Simulate "head not allowed for onsite day 1":
    # - mark head unavailable for onsite on day 1,
    # - keep head available for oncall so feasibility pre-check still passes
    #   (specialist exists among required shifts).
    problem = _build_problem_data(
        make_problem_data=make_problem_data,
        make_preferences=make_preferences,
        doctors=doctors,
        preferences_overrides={
            1: {"preferred_onsite_days": [1]},
        },
        unavailable_onsite_by_doc={1: [1]},
        unavailable_oncall_by_doc={},  # explicit: head still allowed for oncall
    )

    result = scheduler.generate_schedule(problem)
    solution = result.solution

    assert solution.status == SolverStatus.INFEASIBLE
    assert HEAD_COMMITMENT_NOT_ALLOWED in _issue_codes(solution)
    assert result.assignments == []


def test_infeasible_when_head_requests_both_shifts_same_day(make_problem_data, make_preferences):
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=True),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
    }

    problem = _build_problem_data(
        make_problem_data=make_problem_data,
        make_preferences=make_preferences,
        doctors=doctors,
        preferences_overrides={
            1: {"preferred_onsite_days": [1], "preferred_oncall_days": [1]},
        },
    )

    result = scheduler.generate_schedule(problem)
    solution = result.solution

    assert solution.status == SolverStatus.INFEASIBLE
    assert HEAD_COMMITMENT_DOUBLE_SHIFT_SAME_DAY in _issue_codes(solution)
    assert result.assignments == []
