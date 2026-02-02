"""
Core diagnostics — per_doctor[] + rankings determinism.

What we test here (human-friendly):
- per_doctor contains a row for each participant doctor id.
- rankings are stable and deterministic:
  - tie-break uses doctor_id ascending (so ordering does not "jump").
  - top_unhappy uses highest score first (worst), then doctor_id.
  - top_happy uses lowest score first (best), then doctor_id.
"""

from __future__ import annotations

from backend.core.diagnostics import compute_quality
from backend.core.types import DoctorInput, PreferencesInput
from backend.models.common_enums import DoctorRole


def _payload(*, participant_ids: list[int], assignments: list[dict]) -> dict:
    """
    Minimal payload builder for rankings tests.
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
        "meta": {"labels": [], "exceptions": []},
    }


def test_per_doctor_rows_exist_for_all_participants(make_problem_data):
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.resident, is_head=False),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
    }
    prefs = {
        1: PreferencesInput(doctor_id=1),
        2: PreferencesInput(doctor_id=2),
    }

    problem = make_problem_data(days=[1, 2], doctors=doctors, preferences=prefs, participant_doctor_ids={1, 2})
    payload = _payload(participant_ids=[1, 2], assignments=[])

    out = compute_quality(problem=problem, payload=payload)

    per_doctor = out["details"]["per_doctor"]
    assert isinstance(per_doctor, list)
    assert {int(r["doctor_id"]) for r in per_doctor} == {1, 2}

    # Minimal fields required by MVP contract.
    for r in per_doctor:
        assert "doctor_id" in r
        assert "assigned_onsite_total" in r
        assert "assigned_oncall_total" in r
        assert "rest_violations" in r
        assert "preference_fulfillment_pct" in r
        assert "preferred_days_missed" in r


def test_rankings_tie_break_by_doctor_id_is_stable(make_problem_data):
    # We want both doctors to have the same score (tie),
    # so ranking order must fall back to doctor_id ascending.
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.resident, is_head=False),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
    }
    prefs = {
        1: PreferencesInput(doctor_id=1),
        2: PreferencesInput(doctor_id=2),
    }

    problem = make_problem_data(days=[1, 2], doctors=doctors, preferences=prefs, participant_doctor_ids={1, 2})

    # No assignments -> both have equal per-doctor components (score should be equal).
    payload = _payload(participant_ids=[1, 2], assignments=[])

    out = compute_quality(problem=problem, payload=payload)

    rankings = out["details"]["rankings"]
    assert "top_unhappy" in rankings
    assert "top_happy" in rankings

    top_unhappy = rankings["top_unhappy"]
    top_happy = rankings["top_happy"]

    assert len(top_unhappy) >= 2
    assert len(top_happy) >= 2

    # Tie-break: doctor_id ascending.
    assert int(top_unhappy[0]["doctor_id"]) == 1
    assert int(top_unhappy[1]["doctor_id"]) == 2

    assert int(top_happy[0]["doctor_id"]) == 1
    assert int(top_happy[1]["doctor_id"]) == 2
