"""
Core diagnostics — findings[] contract + hard_issues_count.

What we test here (human-friendly):
- findings[] contains small items with: code, severity, context
- hard_issues_count counts ONLY findings with severity="critical"
  (warnings and infos must NOT increase it)

We also check a minimal set of expected codes & context keys.
"""

from __future__ import annotations

from backend.core.diagnostics import compute_quality
from backend.core.types import DoctorInput, PreferencesInput
from backend.models.common_enums import DoctorRole, ShiftType


def _payload(*, participant_ids: list[int], assignments: list[dict], exceptions: list[dict]) -> dict:
    """
    Build a minimal schedule payload for compute_quality().
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
        "inputs_snapshot": {"doctors": doctors_snapshot, "preference_version_id_by_doctor": {}},
        "meta": {"labels": [], "exceptions": list(exceptions)},
    }


def test_hard_issues_count_counts_only_critical(make_problem_data):
    # We want:
    # - 1 critical coverage gap (missing oncall on day 1)
    # - 1 warning rest violation (onsite day1 -> onsite day2)
    # - 1 warning preference miss (preferred oncall day1 not assigned)
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.resident, is_head=False),
    }

    prefs = {
        1: PreferencesInput(
            doctor_id=1,
            preferred_oncall_days=[1],  # will be missed -> preference_miss
            allow_weekend_consecutive_onsite_oncall=False,
        )
    }

    problem = make_problem_data(days=[1, 2], doctors=doctors, preferences=prefs, participant_doctor_ids={1})

    assignments = [
        {"day": 1, "shift_type": ShiftType.onsite.value, "doctor_id": 1},
        {"day": 2, "shift_type": ShiftType.onsite.value, "doctor_id": 1},  # creates onsite->onsite rest violation
        # day 1 oncall missing => critical coverage gap
    ]

    payload = _payload(participant_ids=[1], assignments=assignments, exceptions=[])

    out = compute_quality(problem=problem, payload=payload)

    assert out["summary"]["coverage_missing_required_slots"] == 2  # day1 missing oncall, day2 missing oncall
    assert out["summary"]["hard_issues_count"] >= 1  # at least the coverage gaps

    findings = out["details"]["findings"]
    assert isinstance(findings, list)

    # --- Contract shape checks ---
    for f in findings:
        assert "code" in f
        assert "severity" in f
        assert "context" in f
        assert f["severity"] in ("critical", "warning", "info")
        assert isinstance(f["context"], dict)

    # --- We expect at least one critical coverage gap finding ---
    gap = [f for f in findings if f["code"] == "coverage_missing_required_slot" and f["severity"] == "critical"]
    assert gap, "Expected at least one coverage_missing_required_slot (critical)."

    # Context keys for gaps should include day and shift_type.
    for f in gap:
        assert "day" in f["context"]
        assert "shift_type" in f["context"]
        assert f["context"]["shift_type"] in (ShiftType.onsite.value, ShiftType.oncall.value)

    # --- Rest warnings exist (if your implemented version emits them as findings) ---
    rest = [f for f in findings if f["code"] == "rest_consecutive_violation"]
    assert rest, "Expected rest_consecutive_violation finding (warning)."
    for f in rest:
        assert f["severity"] == "warning"
        assert "doctor_id" in f["context"]
        assert "day" in f["context"]
        assert "kind" in f["context"]
        assert f["context"]["kind"] in ("onsite_onsite", "oncall_oncall", "cross")

    # --- Preference miss warnings exist (if implemented as findings) ---
    pref = [f for f in findings if f["code"] == "preference_miss"]
    assert pref, "Expected preference_miss finding (warning)."
    for f in pref:
        assert f["severity"] == "warning"
        assert "doctor_id" in f["context"]
        assert "day" in f["context"]
        assert "shift_type" in f["context"]
        assert f["context"]["shift_type"] in (ShiftType.onsite.value, ShiftType.oncall.value)

    # --- hard_issues_count must count ONLY critical severities ---
    critical_count = sum(1 for f in findings if f.get("severity") == "critical")
    warning_count = sum(1 for f in findings if f.get("severity") == "warning")
    info_count = sum(1 for f in findings if f.get("severity") == "info")

    assert out["summary"]["hard_issues_count"] == critical_count
    assert warning_count >= 1  # ensure we really produced warnings in this scenario
    assert info_count >= 0
