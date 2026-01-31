# tests/solver/test_diagnostics_coverage.py
"""
Core diagnostics coverage tests.

Goal:
- "Gaps" are ALWAYS counted per slot (onsite + oncall per day).
- Ignore exceptions stored in payload.meta.exceptions DO NOT reduce gap counts in diagnostics.
  They only mark matching gaps with context.was_ignored=True, so UI can show:
  "this gap was accepted during generation" but it is still a real gap.

IMPORTANT (unified codes):
- We require code=issues.COVERAGE_IGNORED_SLOT everywhere.
- Day-level ignore is NOT used anymore (admin ignores slots only).
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
        "inputs_snapshot": {
            "doctors": doctors_snapshot,
            "preference_version_id_by_doctor": {int(did): None for did in participant_ids},
        },
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
    return [f for f in out["details"]["findings"] if f.get("code") == issues.COVERAGE_MISSING_REQUIRED_SLOT]


def _ignored_slot_findings(out: dict) -> list[dict]:
    """
    There should be NO findings with code=COVERAGE_IGNORED_SLOT anymore.

    We keep "was_ignored" markers on gaps, and decision history goes to details.audit[].
    """
    return [f for f in out["details"]["findings"] if f.get("code") == issues.COVERAGE_IGNORED_SLOT]


def _audit_rows(out: dict) -> list[dict]:
    """
    Return details.audit[] rows.

    Contract:
    - Decision history is projected into details.audit[] by diagnostics.
    - Slot-ignore markers like COVERAGE_IGNORED_SLOT must NOT appear here.
    """
    details = out.get("details") or {}
    if not isinstance(details, dict):
        return []
    rows = details.get("audit") or []
    return list(rows) if isinstance(rows, list) else []


def test_coverage_gaps_counted_per_slot(make_problem_data):
    # days 1..2, no assignments -> each day missing onsite + oncall => 2 gaps per day => total 4
    problem = _one_doctor_problem(make_problem_data, days=[1, 2])
    payload = _payload(participant_ids=[1], assignments=[], exceptions=[])

    out = compute_quality(problem=problem, payload=payload)

    assert out["summary"]["coverage_missing_required_slots"] == 4

    gaps = _gap_findings(out)
    assert len(gaps) == 4

    # No informational findings about ignored slots (moved to details.audit[])
    assert _ignored_slot_findings(out) == []

    # None of them should be marked as ignored
    assert all(bool(g.get("context", {}).get("was_ignored")) is False for g in gaps)


def test_coverage_two_ignored_slots_same_day_does_not_hide_gaps_but_marks_them(make_problem_data):
    """
    Slot-only policy replacement for the old "ignored day" behavior.

    If generation ignored BOTH slots on day 1 (onsite + oncall), diagnostics:
    - still reports 4 gaps total (2 per day),
    - marks BOTH gaps on day 1 as was_ignored=True,
    - does NOT emit info findings for ignored slots (audit is separate).
    """
    problem = _one_doctor_problem(make_problem_data, days=[1, 2])
    payload = _payload(
        participant_ids=[1],
        assignments=[],
        exceptions=[
            {"code": issues.COVERAGE_IGNORED_SLOT, "day": 1, "shift_type": ShiftType.onsite.value},
            {"code": issues.COVERAGE_IGNORED_SLOT, "day": 1, "shift_type": ShiftType.oncall.value},
        ],
    )

    out = compute_quality(problem=problem, payload=payload)

    # Still 4 gaps total (2 per day)
    assert out["summary"]["coverage_missing_required_slots"] == 4

    # No informational findings about ignored slots (moved to details.audit[])
    assert _ignored_slot_findings(out) == []

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

    # No informational findings about ignored slots (moved to details.audit[])
    assert _ignored_slot_findings(out) == []

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


def test_audit_is_extracted_from_meta_exceptions_but_ignored_slot_is_not_audit(make_problem_data):
    """
    New rule:
    - payload.meta.exceptions stays as-is (compat),
    - diagnostics extracts "audit-like" records into details.audit[],
    - but it must NOT treat COVERAGE_IGNORED_SLOT as audit.
    """
    problem = _one_doctor_problem(make_problem_data, days=[1, 2])
    payload = _payload(
        participant_ids=[1],
        assignments=[],
        exceptions=[
            # ignore marker (NOT audit)
            {"code": issues.COVERAGE_IGNORED_SLOT, "day": 1, "shift_type": ShiftType.onsite.value},
            # audit-like decision (HAS audit keys -> should go to details.audit[])
            {
                "code": "hard_double_shift_same_day",
                "justification": "Allowed as an exception for training month",
                "accepted_by_user_id": 777,
                "accepted_at": "2026-01-30T10:00:00Z",
            },
        ],
    )

    out = compute_quality(problem=problem, payload=payload)

    # Still: no info findings for ignored slots
    assert _ignored_slot_findings(out) == []

    # Audit is extracted and contains ONLY the audit-like record
    audit = _audit_rows(out)
    assert len(audit) == 1
    assert audit[0].get("code") == "hard_double_shift_same_day"
    assert audit[0].get("accepted_by_user_id") == 777
