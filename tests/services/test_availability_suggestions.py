"""
Unit tests for availability ignore suggestions.

We test the new policy for generation precheck suggestions:
- suggested ignored slots include a REAL day
- NO_SPECIALIST policy uses preferred counts and candidate counts
"""

from __future__ import annotations

import types

import pytest

from backend.core.feasibility import FeasibilityIssue
from backend.core.issues import NO_ONCALL_CANDIDATE, NO_ONSITE_CANDIDATE, NO_SPECIALIST
from backend.core.types import PreferencesInput, ProblemData
from backend.models.common_enums import ShiftType
from backend.services.availability_service import _suggest_ignored_slots_and_reasons

pytestmark = [pytest.mark.services]


def _make_problem_with_prefs(
    *,
    preferred_onsite_by_id: dict[int, list[int]] | None = None,
    preferred_oncall_by_id: dict[int, list[int]] | None = None,
) -> ProblemData:
    preferred_onsite_by_id = preferred_onsite_by_id or {}
    preferred_oncall_by_id = preferred_oncall_by_id or {}

    all_ids = set(preferred_onsite_by_id.keys()) | set(preferred_oncall_by_id.keys())

    prefs: dict[int, PreferencesInput] = {}
    for did in all_ids:
        prefs[int(did)] = PreferencesInput(
            doctor_id=int(did),
            preferred_onsite_days=list(preferred_onsite_by_id.get(int(did), [])),
            preferred_oncall_days=list(preferred_oncall_by_id.get(int(did), [])),
        )

    return ProblemData(
        year=2026,
        month=2,
        days=[],
        weekdays={},
        doctors={},
        preferences=prefs,
        participant_doctor_ids=set(all_ids),
        ignore_slots=set(),
    )


def test_suggest_ignore_onsite_when_no_onsite_candidate(monkeypatch):
    def fake_compute_day_capacity(problem):
        return {3: types.SimpleNamespace(onsite_ids=set(), oncall_ids={1, 2})}

    monkeypatch.setattr("backend.services.availability_service.compute_day_capacity", fake_compute_day_capacity)

    problem = _make_problem_with_prefs()
    issues = [FeasibilityIssue(day=3, code=NO_ONSITE_CANDIDATE, message="x")]

    suggested, reasons = _suggest_ignored_slots_and_reasons(problem=problem, precheck_issues=issues)

    assert reasons == [NO_ONSITE_CANDIDATE]
    assert len(suggested) == 1
    assert int(suggested[0].day) == 3
    assert suggested[0].shift_type == ShiftType.onsite


def test_suggest_ignore_oncall_when_no_oncall_candidate(monkeypatch):
    def fake_compute_day_capacity(problem):
        return {7: types.SimpleNamespace(onsite_ids={1, 2}, oncall_ids=set())}

    monkeypatch.setattr("backend.services.availability_service.compute_day_capacity", fake_compute_day_capacity)

    problem = _make_problem_with_prefs()
    issues = [FeasibilityIssue(day=7, code=NO_ONCALL_CANDIDATE, message="x")]

    suggested, reasons = _suggest_ignored_slots_and_reasons(problem=problem, precheck_issues=issues)

    assert reasons == [NO_ONCALL_CANDIDATE]
    assert len(suggested) == 1
    assert int(suggested[0].day) == 7
    assert suggested[0].shift_type == ShiftType.oncall


def test_no_specialist_prefers_slot_with_more_preferred(monkeypatch):
    def fake_compute_day_capacity(problem):
        return {10: types.SimpleNamespace(onsite_ids={1, 2, 3}, oncall_ids={4, 5, 6})}

    monkeypatch.setattr("backend.services.availability_service.compute_day_capacity", fake_compute_day_capacity)

    # onsite has 2 preferred, oncall has 0 preferred -> ignore oncall
    problem = _make_problem_with_prefs(preferred_onsite_by_id={1: [10], 2: [10]})
    issues = [FeasibilityIssue(day=10, code=NO_SPECIALIST, message="x")]

    suggested, reasons = _suggest_ignored_slots_and_reasons(problem=problem, precheck_issues=issues)

    assert reasons == [NO_SPECIALIST]
    assert len(suggested) == 1
    assert int(suggested[0].day) == 10
    assert suggested[0].shift_type == ShiftType.oncall


def test_no_specialist_tie_preferred_uses_total_candidates(monkeypatch):
    def fake_compute_day_capacity(problem):
        # onsite has more candidates than oncall
        return {11: types.SimpleNamespace(onsite_ids={1, 2, 3, 4}, oncall_ids={5})}

    monkeypatch.setattr("backend.services.availability_service.compute_day_capacity", fake_compute_day_capacity)

    # preferred tie: 0 vs 0 -> use total candidates -> ignore oncall
    problem = _make_problem_with_prefs()
    issues = [FeasibilityIssue(day=11, code=NO_SPECIALIST, message="x")]

    suggested, reasons = _suggest_ignored_slots_and_reasons(problem=problem, precheck_issues=issues)

    assert reasons == [NO_SPECIALIST]
    assert len(suggested) == 1
    assert int(suggested[0].day) == 11
    assert suggested[0].shift_type == ShiftType.oncall


def test_no_specialist_full_tie_falls_back_to_oncall(monkeypatch):
    def fake_compute_day_capacity(problem):
        # totals tie
        return {12: types.SimpleNamespace(onsite_ids={1, 2}, oncall_ids={3, 4})}

    monkeypatch.setattr("backend.services.availability_service.compute_day_capacity", fake_compute_day_capacity)

    # preferred tie: 0 vs 0, total tie -> fallback -> ignore oncall
    problem = _make_problem_with_prefs()
    issues = [FeasibilityIssue(day=12, code=NO_SPECIALIST, message="x")]

    suggested, reasons = _suggest_ignored_slots_and_reasons(problem=problem, precheck_issues=issues)

    assert reasons == [NO_SPECIALIST]
    assert len(suggested) == 1
    assert int(suggested[0].day) == 12
    assert suggested[0].shift_type == ShiftType.oncall
