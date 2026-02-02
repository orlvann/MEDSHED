# tests/solver/test_issues_counts_and_risk.py
"""
Unit tests for shared issues + availability risk helpers (current policy).

Current policy (see backend/core/issues.py):
- We do NOT use counts-only feasibility classification (identity is required).
- We do NOT have NO_CANDIDATES_FOR_DAY anymore.
  If a day has no candidates, we report per-slot gaps:
    - NO_ONSITE_CANDIDATE
    - NO_ONCALL_CANDIDATE
  and (when BOTH shifts are required) also:
    - NO_SPECIALIST
- RiskLevel is treated as: ok / critical (alert removed).
"""

from __future__ import annotations

import pytest

from backend.core.issues import (
    NO_ONCALL_CANDIDATE,
    NO_ONSITE_CANDIDATE,
    NO_SPECIALIST,
    classify_availability_risk_with_reasons,
    classify_feasibility_issues_for_day,
)
from backend.models.common_enums import DoctorRole, RiskLevel

pytestmark = [pytest.mark.solver]


def test_feasibility_when_day_is_totally_empty_emits_slot_gaps_and_no_specialist():
    """
    If BOTH shifts are required and both candidate sets are empty, we emit:
    - NO_ONSITE_CANDIDATE
    - NO_ONCALL_CANDIDATE
    - NO_SPECIALIST  (because both shifts are required and union has no specialist)
    """
    issues = classify_feasibility_issues_for_day(
        onsite_ids=set(),
        oncall_ids=set(),
        doctor_role_by_id={},
        onsite_required=True,
        oncall_required=True,
    )

    assert issues == [NO_ONSITE_CANDIDATE, NO_ONCALL_CANDIDATE, NO_SPECIALIST]


def test_feasibility_when_only_onsite_missing_emits_no_onsite_candidate_only():
    """
    If onsite is missing but oncall has candidates (including a specialist),
    we emit only NO_ONSITE_CANDIDATE (and NOT NO_SPECIALIST).
    """
    doctor_role_by_id = {
        1: DoctorRole.specialist,  # specialist exists among REQUIRED candidates (oncall)
    }

    issues = classify_feasibility_issues_for_day(
        onsite_ids=set(),
        oncall_ids={1},
        doctor_role_by_id=doctor_role_by_id,
        onsite_required=True,
        oncall_required=True,
    )

    assert issues == [NO_ONSITE_CANDIDATE]


def test_availability_risk_ok_has_no_issues():
    """
    High availability day:
    - both required slots have candidates,
    - union contains at least one specialist
    => risk=ok and issues=[].
    """
    doctor_role_by_id = {
        1: DoctorRole.specialist,
        2: DoctorRole.resident,
        3: DoctorRole.resident,
    }

    details = classify_availability_risk_with_reasons(
        onsite_ids={1, 2},
        oncall_ids={1, 3},
        doctor_role_by_id=doctor_role_by_id,
        onsite_required=True,
        oncall_required=True,
    )

    assert details.risk == RiskLevel.ok
    assert details.issues == []


def test_availability_risk_empty_day_is_critical_and_has_expected_issues():
    """
    Empty day:
    - both required slots have zero candidates -> critical
    - issues contain NO_ONSITE_CANDIDATE, NO_ONCALL_CANDIDATE, and NO_SPECIALIST
    """
    details = classify_availability_risk_with_reasons(
        onsite_ids=set(),
        oncall_ids=set(),
        doctor_role_by_id={},
        onsite_required=True,
        oncall_required=True,
    )

    assert details.risk == RiskLevel.critical
    assert details.issues == [NO_ONSITE_CANDIDATE, NO_ONCALL_CANDIDATE, NO_SPECIALIST]
