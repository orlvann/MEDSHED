"""
Unit tests for _apply_head_commitment_resolutions (in-place mutation).

What we verify:
1) For a resolved slot (day + shift_type), the chosen head keeps the day
   in the correct preferred_*_days list, and other heads lose it.
2) Non-head doctors are NOT modified by this rule.
3) For oncall resolutions we modify preferred_oncall_days (not onsite).
4) Duplicates for the same slot keep the LAST resolution (deterministic).
5) Invalid chosen_head_id (not a head in participant pool) raises a stable error code.

Why unit tests (no DB):
- This logic must be fast, deterministic, and independent from persistence.
"""

from __future__ import annotations

import pytest

from backend.core.types import DoctorInput, PreferencesInput, ProblemData
from backend.models.common_enums import DoctorRole, ShiftType
from backend.models.schemas.schedule import HeadCommitmentResolution
from backend.services.scheduling_service import _apply_head_commitment_resolutions


def _mk_problem() -> ProblemData:
    """
    Create a minimal ProblemData with:
    - 2 heads: 101, 102
    - 1 non-head: 201
    - all in participant pool
    - both heads have conflicting onsite commitment day=5
    - non-head also has day=5 (should stay untouched)
    """
    doctors = {
        101: DoctorInput(id=101, role=DoctorRole.specialist, is_head=True, is_active=True),
        102: DoctorInput(id=102, role=DoctorRole.specialist, is_head=True, is_active=True),
        201: DoctorInput(id=201, role=DoctorRole.resident, is_head=False, is_active=True),
    }

    preferences = {
        101: PreferencesInput(doctor_id=101, preferred_onsite_days=[5], preferred_oncall_days=[]),
        102: PreferencesInput(doctor_id=102, preferred_onsite_days=[5], preferred_oncall_days=[]),
        201: PreferencesInput(doctor_id=201, preferred_onsite_days=[5], preferred_oncall_days=[]),
    }

    return ProblemData(
        year=2026,
        month=2,
        days=[1, 2, 3, 4, 5],
        weekdays={1: 0, 2: 1, 3: 2, 4: 3, 5: 4},
        doctors=doctors,
        preferences=preferences,
        participant_doctor_ids={101, 102, 201},
        ignore_slots=set(),
    )


def test_onsite_resolution_keeps_day_only_for_chosen_head() -> None:
    """
    It should remove the day from OTHER heads' preferred_onsite_days,
    keep/ensure it for the chosen head, and NOT modify non-head doctors.
    """
    problem = _mk_problem()

    resolutions = [
        HeadCommitmentResolution(day=5, shift_type=ShiftType.onsite, chosen_head_id=101),
    ]

    _apply_head_commitment_resolutions(problem, resolutions)

    assert problem.preferences[101].preferred_onsite_days == [5]
    assert problem.preferences[102].preferred_onsite_days == []
    # Non-head untouched:
    assert problem.preferences[201].preferred_onsite_days == [5]


def test_oncall_resolution_targets_preferred_oncall_days_only() -> None:
    """
    For shift_type=oncall, the helper must edit preferred_oncall_days
    (and must NOT touch preferred_onsite_days).
    """
    problem = _mk_problem()

    # create a conflict on oncall day=12
    problem.preferences[101].preferred_oncall_days = [12]
    problem.preferences[102].preferred_oncall_days = [12]

    resolutions = [
        HeadCommitmentResolution(day=12, shift_type=ShiftType.oncall, chosen_head_id=102),
    ]

    _apply_head_commitment_resolutions(problem, resolutions)

    assert problem.preferences[102].preferred_oncall_days == [12]
    assert problem.preferences[101].preferred_oncall_days == []

    # onsite stays as it was after _mk_problem()
    assert problem.preferences[101].preferred_onsite_days == [5]
    assert problem.preferences[102].preferred_onsite_days == [5]


def test_last_resolution_wins_for_same_slot() -> None:
    """
    If the request contains multiple resolutions for the same (day, shift_type),
    the helper must keep the LAST one (deterministic behavior).
    """
    problem = _mk_problem()

    resolutions = [
        HeadCommitmentResolution(day=5, shift_type=ShiftType.onsite, chosen_head_id=101),
        HeadCommitmentResolution(day=5, shift_type=ShiftType.onsite, chosen_head_id=102),  # last wins
    ]

    _apply_head_commitment_resolutions(problem, resolutions)

    assert problem.preferences[102].preferred_onsite_days == [5]
    assert problem.preferences[101].preferred_onsite_days == []


def test_invalid_chosen_head_raises_stable_code() -> None:
    """
    If chosen_head_id is not a head inside participant pool, we must fail fast
    with a stable ValueError code for the router.
    """
    problem = _mk_problem()

    resolutions = [
        HeadCommitmentResolution(day=5, shift_type=ShiftType.onsite, chosen_head_id=201),  # non-head
    ]

    with pytest.raises(ValueError) as ex:
        _apply_head_commitment_resolutions(problem, resolutions)

    assert str(ex.value) == "invalid_head_commitment_resolution"
