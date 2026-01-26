# tests/solver/test_diagnostics_coverage.py
"""
Core diagnostics coverage tests.

Goal:
- "Gaps" are ALWAYS counted per slot (onsite + oncall per day).
- Ignore exceptions stored in payload.meta.exceptions DO NOT reduce gap counts in diagnostics.
  They only mark matching gaps with context.was_ignored=True, so UI can show:
  "this gap was accepted during generation" but it is still a real gap.

We also keep info findings about what was ignored during generation.

IMPORTANT (unified codes):
- We require code=issues.COVERAGE_IGNORED_DAY / issues.COVERAGE_IGNORED_SLOT everywhere.
- We do NOT accept legacy "ignored_day"/"ignored_slot" in these tests anymore.
"""

from __future__ import annotations

from backend.core import issues
from backend.core.diagnostics import compute_quality
from backend.core.types import DoctorInput
from backend.models.common_enums import DoctorRole, ShiftType


def _payload(*, participant_ids: list[int], assignments: list[dict], exceptions: list[dict]) -> dict:
    """
    Build a minimal schedule payload for compute_quality().

    Notes:
    - inputs_snapshot is not needed for coverage math, but we include it to match real payload shape.
    """
    doctors_snapshot = {
        str(did): {"display_name": f"Doctor {did}", "role": "resident", "is_head": False} for did in participant_ids
    }
    return {
        "participant_doctor_ids": list(participant_ids),
        "assignments": list(assignments),
        "inputs_snapshot": {"doctors": doctors_snapshot, "preference_version_id_by_doctor": {}},
        "meta": {"labels": [], "exceptions": list(exceptions)},
    }


def _one_doctor_problem(make_problem_data, *, days: list[int]):
    """
    Build ProblemData for a tiny deterministic scenario:
    - 1 doctor (resident)
    - selected days only
    """
    return make_problem_data(
        days=list(days),
        doctors={1: DoctorInput(id=1, role=DoctorRole.resident, is_head=False)},
        participant_doctor_ids={1},
    )


def _gap_findings(out: dict) -> list[dict]:
    """Return only gap findings (missing required slot)."""
    return [f for f in out["details"]["findings"] if f.get("code") == "coverage_missing_required_slot"]


def _info_findings(out: dict) -> list[dict]:
    """Return only info findings."""
    return [f for f in out["details"]["findings"] if f.get("severity") == "info"]


def test_coverage_gaps_counted_per_slot(make_problem_data):
    # days 1..2, no assignments -> each day missing onsite + oncall => 2 gaps per day => total 4
    problem = _one_doctor_problem(make_problem_data, days=[1, 2])
    payload = _payload(participant_ids=[1], assignments=[], exceptions=[])

    out = compute_quality(problem=problem, payload=payload)

    assert out["summary"]["coverage_missing_required_slots"] == 4

    gaps = _gap_findings(out)
    assert len(gaps) == 4

    # None of them should be marked as ignored
    assert all(bool(g.get("context", {}).get("was_ignored")) is False for g in gaps)


def test_coverage_ignored_day_does_not_hide_gaps_but_marks_them(make_problem_data):
    # coverage_ignored_day(1) does NOT remove requirements in diagnostics.
    # Day 1 still has 2 gaps, but both should be marked was_ignored=True.
    # Day 2 still has 2 gaps, was_ignored=False.
    problem = _one_doctor_problem(make_problem_data, days=[1, 2])
    payload = _payload(
        participant_ids=[1],
        assignments=[],
        exceptions=[{"code": issues.COVERAGE_IGNORED_DAY, "day": 1}],
    )

    out = compute_quality(problem=problem, payload=payload)

    # Still 4 gaps total (2 per day)
    assert out["summary"]["coverage_missing_required_slots"] == 4

    # We keep an info finding that says day 1 was ignored during generation
    infos = _info_findings(out)
    assert any(
        f.get("code") == issues.COVERAGE_IGNORED_DAY and int(f.get("context", {}).get("day", 0)) == 1 for f in infos
    )

    gaps = _gap_findings(out)
    assert len(gaps) == 4

    day1 = [g for g in gaps if int(g.get("context", {}).get("day", 0)) == 1]
    assert len(day1) == 2
    assert all(bool(g.get("context", {}).get("was_ignored")) is True for g in day1)

    day2 = [g for g in gaps if int(g.get("context", {}).get("day", 0)) == 2]
    assert len(day2) == 2
    assert all(bool(g.get("context", {}).get("was_ignored")) is False for g in day2)


def test_coverage_ignored_slot_does_not_hide_gaps_but_marks_that_slot(make_problem_data):
    # coverage_ignored_slot(2, onsite) does NOT remove requirements in diagnostics.
    # Day 2 still has 2 gaps, but ONLY the onsite gap should have was_ignored=True.
    problem = _one_doctor_problem(make_problem_data, days=[1, 2])
    payload = _payload(
        participant_ids=[1],
        assignments=[],
        exceptions=[{"code": issues.COVERAGE_IGNORED_SLOT, "day": 2, "shift_type": ShiftType.onsite.value}],
    )

    out = compute_quality(problem=problem, payload=payload)

    # Still 4 gaps total (2 per day)
    assert out["summary"]["coverage_missing_required_slots"] == 4

    # We keep an info finding that says this slot was ignored during generation
    infos = _info_findings(out)
    assert any(
        f.get("code") == issues.COVERAGE_IGNORED_SLOT
        and int(f.get("context", {}).get("day", 0)) == 2
        and f.get("context", {}).get("shift_type") == "onsite"
        for f in infos
    )

    gaps = _gap_findings(out)
    assert len(gaps) == 4

    day2_onsite = [
        g
        for g in gaps
        if int(g.get("context", {}).get("day", 0)) == 2 and g.get("context", {}).get("shift_type") == "onsite"
    ]
    assert len(day2_onsite) == 1
    assert bool(day2_onsite[0].get("context", {}).get("was_ignored")) is True

    day2_oncall = [
        g
        for g in gaps
        if int(g.get("context", {}).get("day", 0)) == 2 and g.get("context", {}).get("shift_type") == "oncall"
    ]
    assert len(day2_oncall) == 1
    assert bool(day2_oncall[0].get("context", {}).get("was_ignored")) is False
