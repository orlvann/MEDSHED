# test_issues_counts_and_risk.py
"""
Unit tests for shared issues + availability risk helpers.

Goals:
- NO_CANDIDATES_FOR_DAY should NOT be duplicated with NO_ONSITE/NO_ONCALL
  when both totals are zero (single clear reason).
- classify_availability_risk_with_reasons should be stable and not crash.
"""

from __future__ import annotations

import pytest

from backend.core.issues import (
    NO_CANDIDATES_FOR_DAY,
    NO_ONCALL_CANDIDATE,
    NO_ONSITE_CANDIDATE,
    NO_SPECIALIST,
    classify_availability_risk_with_reasons,
    classify_feasibility_issues_for_counts,
)
from backend.models.common_enums import RiskLevel

pytestmark = [pytest.mark.solver]


def test_counts_when_day_is_totally_empty_returns_only_no_candidates_for_day():
    """
    If total_onsite=0 AND total_oncall=0, we want ONE clear issue:
    - NO_CANDIDATES_FOR_DAY
    and we do NOT duplicate it with NO_ONSITE/NO_ONCALL.
    """
    issues = classify_feasibility_issues_for_counts(
        total_onsite=0,
        total_oncall=0,
        total_specialists=0,
    )

    assert issues == [NO_CANDIDATES_FOR_DAY], f"Expected a single clear reason, got: {issues}"


def test_counts_when_only_onsite_missing_emits_no_onsite_candidate_only():
    """
    If only onsite is missing (0) but oncall exists, we emit NO_ONSITE_CANDIDATE,
    and we do NOT emit NO_CANDIDATES_FOR_DAY.
    """
    issues = classify_feasibility_issues_for_counts(
        total_onsite=0,
        total_oncall=2,
        total_specialists=1,
    )

    assert NO_ONSITE_CANDIDATE in issues
    assert NO_CANDIDATES_FOR_DAY not in issues


def test_availability_risk_ok_has_no_issues():
    """
    For a very high availability day, risk should be OK and issues should be empty.
    (We intentionally use large numbers to avoid depending on thresholds.)
    """
    details = classify_availability_risk_with_reasons(
        spec_onsite=50,
        res_onsite=50,
        spec_oncall=50,
        res_oncall=50,
    )

    assert details.risk == RiskLevel.ok
    assert details.issues == []


def test_availability_risk_empty_day_is_critical_and_has_no_candidates_issue():
    """
    For an empty day, risk should not crash and issues should contain NO_CANDIDATES_FOR_DAY.
    Also, NO_CANDIDATES_FOR_DAY should not be duplicated with NO_ONSITE/NO_ONCALL.
    """
    details = classify_availability_risk_with_reasons(
        spec_onsite=0,
        res_onsite=0,
        spec_oncall=0,
        res_oncall=0,
    )

    assert details.risk in (RiskLevel.alert, RiskLevel.critical)  # depends on your risk thresholds
    assert NO_CANDIDATES_FOR_DAY in details.issues
    assert NO_ONSITE_CANDIDATE not in details.issues
    assert NO_ONCALL_CANDIDATE not in details.issues
    assert NO_SPECIALIST not in details.issues
