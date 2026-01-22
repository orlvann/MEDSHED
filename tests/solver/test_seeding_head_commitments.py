# tests/solver/test_seeding_head_commitments.py
"""
Tests for "Head commitments" (must-have head preferred slots).

Rule summary:

* If head preferred slot is ignored -> INFEASIBLE + issue
* If head preferred slot is not allowed -> INFEASIBLE + issue
* If multiple heads prefer the same slot -> INFEASIBLE + issue
* If the same head prefers onsite and oncall on the same day -> INFEASIBLE + issue

We test this through engine.build_and_solve(), because engine validates commitments
before building/solving the CP model.
"""

from __future__ import annotations

import pytest

from backend.core import engine
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


def _build_problem_model(
    *,
    make_hard_model,
    make_preferences,
    doctors: dict[int, DoctorInput],
    preferences_overrides: dict[int, dict],
    allowed_slots: dict[tuple[int, ShiftType], list[int]],
    ignore_slots: set[tuple[int, ShiftType]] | None = None,
):
    """
    Build a tiny HardModel for commitment validation tests.

    preferences_overrides format example:
        {
            1: {"preferred_onsite_days": [1]},
            2: {"preferred_oncall_days": [2]},
        }
    """
    preferences = make_preferences(doctors=doctors)

    # Apply overrides in a safe, explicit way (no magic).
    for doc_id, overrides in preferences_overrides.items():
        pref = preferences[doc_id]
        for field_name, value in overrides.items():
            setattr(pref, field_name, value)

    model = make_hard_model(
        days=[1],
        doctors=doctors,
        preferences=preferences,
        participant_doctor_ids=set(doctors.keys()),
        ignore_days=set(),
        ignore_slots=set(ignore_slots or set()),
        allowed_slots=allowed_slots,
    )
    return model


def test_infeasible_when_two_heads_commit_same_slot(make_hard_model, make_preferences):
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=True),
        2: DoctorInput(id=2, role=DoctorRole.specialist, is_head=True),
        3: DoctorInput(id=3, role=DoctorRole.resident, is_head=False),
    }

    model = _build_problem_model(
        make_hard_model=make_hard_model,
        make_preferences=make_preferences,
        doctors=doctors,
        preferences_overrides={
            1: {"preferred_onsite_days": [1]},
            2: {"preferred_onsite_days": [1]},
        },
        allowed_slots={
            (1, ShiftType.onsite): [1, 2, 3],
            (1, ShiftType.oncall): [1, 2, 3],
        },
    )

    solution = engine.build_and_solve(model)

    assert solution.status == SolverStatus.INFEASIBLE
    assert HEAD_COMMITMENT_CONFLICT in _issue_codes(solution)


def test_infeasible_when_head_commitment_targets_ignored_slot(make_hard_model, make_preferences):
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=True),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
    }

    model = _build_problem_model(
        make_hard_model=make_hard_model,
        make_preferences=make_preferences,
        doctors=doctors,
        preferences_overrides={
            1: {"preferred_onsite_days": [1]},
        },
        ignore_slots={(1, ShiftType.onsite)},
        allowed_slots={
            # In production this key is typically missing for ignored slots,
            # but we keep it explicit here to keep the model tiny.
            (1, ShiftType.onsite): [1, 2],
            (1, ShiftType.oncall): [1, 2],
        },
    )

    solution = engine.build_and_solve(model)

    assert solution.status == SolverStatus.INFEASIBLE
    assert HEAD_COMMITMENT_IGNORED_SLOT in _issue_codes(solution)


def test_infeasible_when_head_commitment_is_not_allowed(make_hard_model, make_preferences):
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=True),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
    }

    model = _build_problem_model(
        make_hard_model=make_hard_model,
        make_preferences=make_preferences,
        doctors=doctors,
        preferences_overrides={
            1: {"preferred_onsite_days": [1]},
        },
        allowed_slots={
            # Head (id=1) is NOT in allowed onsite candidates.
            (1, ShiftType.onsite): [2],
            (1, ShiftType.oncall): [1, 2],
        },
    )

    solution = engine.build_and_solve(model)

    assert solution.status == SolverStatus.INFEASIBLE
    assert HEAD_COMMITMENT_NOT_ALLOWED in _issue_codes(solution)


def test_infeasible_when_head_requests_both_shifts_same_day(make_hard_model, make_preferences):
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=True),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
    }

    model = _build_problem_model(
        make_hard_model=make_hard_model,
        make_preferences=make_preferences,
        doctors=doctors,
        preferences_overrides={
            1: {"preferred_onsite_days": [1], "preferred_oncall_days": [1]},
        },
        allowed_slots={
            (1, ShiftType.onsite): [1, 2],
            (1, ShiftType.oncall): [1, 2],
        },
    )

    solution = engine.build_and_solve(model)

    assert solution.status == SolverStatus.INFEASIBLE
    assert HEAD_COMMITMENT_DOUBLE_SHIFT_SAME_DAY in _issue_codes(solution)
