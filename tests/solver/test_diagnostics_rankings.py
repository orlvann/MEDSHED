"""
Core diagnostics — per_doctor[] + rankings determinism.

What we test here (human-friendly):
- per_doctor contains a row for each participant doctor id.
- rankings are stable and deterministic:
  - ranking order is derived from per_doctor[].score (so it will never "jump" randomly)
  - tie-break uses doctor_id ascending when scores are equal
  - top_unhappy is sorted by score ascending (lower score = worse), then doctor_id
  - top_happy is sorted by score descending (higher score = better), then doctor_id

IMPORTANT:
- We do NOT assume "no assignments => tie".
  Diagnostics score can include fairness/expected terms that may differ per doctor even with zero assignments.
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
        assert "score" in r  # rankings derive from this


def test_rankings_are_consistent_with_per_doctor_scores_and_stable(make_problem_data):
    """
    Rankings must be deterministic and must match the documented sorting rules.
    We do not assume a tie; we derive the expected order from per_doctor[].score.
    """
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.resident, is_head=False),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
    }
    prefs = {
        1: PreferencesInput(doctor_id=1),
        2: PreferencesInput(doctor_id=2),
    }

    problem = make_problem_data(days=[1, 2], doctors=doctors, preferences=prefs, participant_doctor_ids={1, 2})

    # No assignments is still a valid snapshot; score may still differ (e.g. fairness expected terms).
    payload = _payload(participant_ids=[1, 2], assignments=[])

    out = compute_quality(problem=problem, payload=payload)

    rankings = out["details"]["rankings"]
    assert "top_unhappy" in rankings
    assert "top_happy" in rankings

    top_unhappy = rankings["top_unhappy"]
    top_happy = rankings["top_happy"]

    assert len(top_unhappy) >= 2
    assert len(top_happy) >= 2

    per_doctor = out["details"]["per_doctor"]
    assert len(per_doctor) >= 2

    # Build "expected" orders directly from per_doctor (single source of truth).
    # Unhappy: lowest score first, tie-break doctor_id ascending.
    expected_unhappy = sorted(per_doctor, key=lambda r: (float(r["score"]), int(r["doctor_id"])))
    # Happy: highest score first, tie-break doctor_id ascending.
    expected_happy = sorted(per_doctor, key=lambda r: (-float(r["score"]), int(r["doctor_id"])))

    assert int(top_unhappy[0]["doctor_id"]) == int(expected_unhappy[0]["doctor_id"])
    assert int(top_unhappy[1]["doctor_id"]) == int(expected_unhappy[1]["doctor_id"])

    assert int(top_happy[0]["doctor_id"]) == int(expected_happy[0]["doctor_id"])
    assert int(top_happy[1]["doctor_id"]) == int(expected_happy[1]["doctor_id"])

    # Extra safety: if there is an actual tie, verify tie-break by doctor_id.
    # (This is conditional, so we don't force a tie in this scenario.)
    if float(expected_happy[0]["score"]) == float(expected_happy[1]["score"]):
        assert int(expected_happy[0]["doctor_id"]) < int(expected_happy[1]["doctor_id"])
    if float(expected_unhappy[0]["score"]) == float(expected_unhappy[1]["score"]):
        assert int(expected_unhappy[0]["doctor_id"]) < int(expected_unhappy[1]["doctor_id"])
