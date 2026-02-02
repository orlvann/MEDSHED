# tests/solver/test_scheduler_precheck_priority.py
"""
Scheduler tests: phase ordering guarantees.

We want a clear pipeline:
1) feasibility.analyze_problem(problem) runs first (cheap pre-check)
2) build_hard_model(problem)
3) seeding.validate_head_commitments(hard_model)
4) engine.build_and_solve(hard_model)

This file tests that:
- if feasibility pre-check returns issues, scheduler stops early
- head commitment validation is NOT executed (and its issues are NOT returned)
"""

from __future__ import annotations

import pytest

from backend.core import scheduler
from backend.core.issues import HEAD_COMMITMENT_NOT_ALLOWED, NO_ONSITE_CANDIDATE
from backend.core.types import DoctorInput, SolverStatus
from backend.models.common_enums import DoctorRole

pytestmark = [pytest.mark.solver]


def _issue_codes(solution) -> list[str]:
    """Helper: extract issue codes from solution (safe when issues is None)."""
    return [i.code for i in (solution.issues or [])]


def test_scheduler_stops_on_feasibility_precheck_before_head_commitments(make_problem_data, make_preferences):
    """
    We create a case where:
    - feasibility pre-check detects NO_ONSITE_CANDIDATE (onsite required, zero candidates)
    - ALSO, the head has a preferred onsite day that would be invalid later
      (head commitment would become NOT_ALLOWED)

    Expected behavior:
    - scheduler returns INFEASIBLE due to pre-check
    - returned issues include NO_ONSITE_CANDIDATE
    - returned issues do NOT include any head_commitment_* codes
    """
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=True),  # head
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
    }

    # Build preferences and force:
    # - both doctors unavailable for onsite on day 1 => NO_ONSITE_CANDIDATE
    # - head prefers onsite day 1 => would later be NOT_ALLOWED in allowed_slots
    preferences = make_preferences(
        doctors=doctors,
        unavailable_onsite_by_doc={1: [1], 2: [1]},
        unavailable_oncall_by_doc={},  # keep oncall available so we isolate the onsite issue
    )
    setattr(preferences[1], "preferred_onsite_days", [1])

    problem = make_problem_data(
        days=[1],
        doctors=doctors,
        preferences=preferences,
        participant_doctor_ids=set(doctors.keys()),
        ignore_slots=set(),  # onsite is required
    )

    result = scheduler.generate_schedule(problem)
    solution = result.solution

    assert solution.status == SolverStatus.INFEASIBLE

    codes = _issue_codes(solution)
    assert NO_ONSITE_CANDIDATE in codes

    # The key guarantee: we should NOT mix later-phase head commitment issues here.
    assert HEAD_COMMITMENT_NOT_ALLOWED not in codes

    # And since infeasible, scheduler should not return assignments.
    assert result.assignments == []
