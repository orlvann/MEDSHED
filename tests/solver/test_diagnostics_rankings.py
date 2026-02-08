# tests/solver/test_diagnostics_rankings.py
"""
Core diagnostics — per_doctor[] + rankings determinism.

What we test here (human-friendly, UPDATED to new UI rankings):
- per_doctor contains a row for each participant doctor id.
- rankings are stable and deterministic:
  - every doctor appears in EXACTLY ONE list: top_happy OR top_unhappy
  - happy list order:
      ui_stars DESC, then alphabetical by "surname" (last token of display_name),
      then display_name, then doctor_id (stable tie-break)
  - unhappy list order:
      ui_stars ASC, then alphabetical by "surname" (last token of display_name),
      then display_name, then doctor_id

Notes:
- Ranking "score" is UI stars (for backward-compat schema), not solver score_points.
"""

from __future__ import annotations

from backend.core.diagnostics import compute_quality
from backend.core.types import DoctorInput, PreferencesInput
from backend.models.common_enums import DoctorRole
from backend.models.constants.diagnostics_reason_codes import ALL_REASON_CODES


def _payload(
    *,
    participant_ids: list[int],
    assignments: list[dict],
    display_names: dict[int, str] | None = None,
) -> dict:
    """
    Minimal payload builder for rankings tests.

    display_names:
    - optional mapping {doctor_id -> display_name}
    - used to test human-like alphabetical sorting by surname
    """
    names = dict(display_names or {})

    doctors_snapshot = {
        str(did): {
            "display_name": str(names.get(did, f"Doctor {did}")),
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


def _safe_str(v) -> str:
    try:
        s = str(v) if v is not None else ""
    except Exception:
        s = ""
    return s.strip()


def _last_name_key(display_name: str) -> str:
    """
    Sorting "surname" key:
    - take last token of display_name (simple human-ish heuristic)
    """
    dn = _safe_str(display_name)
    if not dn:
        return ""
    parts = [p for p in dn.split(" ") if p]
    if not parts:
        return dn.lower()
    return str(parts[-1]).lower()


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

    # Minimal fields required by contract.
    for r in per_doctor:
        assert "doctor_id" in r
        assert "display_name" in r
        assert "assigned_onsite_total" in r
        assert "assigned_oncall_total" in r
        assert "rest_violations" in r
        assert "preference_fulfillment_pct" in r
        assert "preferred_days_missed" in r
        assert "score" in r  # legacy points; rankings no longer derive from this
        assert "ui_stars" in r
        assert "ui_reasons_codes" in r
        assert "ui_components" in r


def test_rankings_are_consistent_with_per_doctor_scores_and_stable(make_problem_data):
    """
    Rankings must be deterministic and must match the documented sorting rules (UPDATED).
    Each doctor must be in exactly one list: happy OR unhappy.
    """
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.resident, is_head=False),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
        3: DoctorInput(id=3, role=DoctorRole.resident, is_head=False),
        4: DoctorInput(id=4, role=DoctorRole.resident, is_head=False),
    }
    prefs = {
        1: PreferencesInput(doctor_id=1),
        2: PreferencesInput(doctor_id=2),
        3: PreferencesInput(doctor_id=3),
        4: PreferencesInput(doctor_id=4),
    }

    problem = make_problem_data(
        days=[1, 2, 3, 4],
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids={1, 2, 3, 4},
    )

    # Provide names so surname ordering is testable/deterministic.
    display_names = {
        1: "Jan Zebra",
        2: "Ala Apple",
        3: "Ola Mango",
        4: "Ewa Berry",
    }

    # Make 3 and 4 clearly unhappy (double shift); 1 and 2 likely happy.
    assignments = [
        {"doctor_id": 3, "day": 1, "shift_type": "onsite"},
        {"doctor_id": 3, "day": 1, "shift_type": "oncall"},  # double shift
        {"doctor_id": 4, "day": 2, "shift_type": "onsite"},
        {"doctor_id": 4, "day": 2, "shift_type": "oncall"},  # double shift
    ]

    payload = _payload(participant_ids=[1, 2, 3, 4], assignments=assignments, display_names=display_names)

    out = compute_quality(problem=problem, payload=payload)

    rankings = out["details"]["rankings"]
    assert "top_unhappy" in rankings
    assert "top_happy" in rankings

    top_unhappy = list(rankings["top_unhappy"])
    top_happy = list(rankings["top_happy"])

    per_doctor = out["details"]["per_doctor"]
    assert len(per_doctor) >= 4

    # Everyone must be in exactly one list
    ids_unhappy = {int(r["doctor_id"]) for r in top_unhappy}
    ids_happy = {int(r["doctor_id"]) for r in top_happy}
    assert ids_unhappy.isdisjoint(ids_happy)
    assert ids_unhappy.union(ids_happy) == {int(r["doctor_id"]) for r in per_doctor}

    # Build expected orders from per_doctor and the NEW sorting rules.
    # Partition rule must match diagnostics:
    # happy: ui_stars >= 4
    # unhappy: ui_stars <= 3
    HAPPY_MIN_STARS = 4
    expected_happy = [r for r in per_doctor if int(r.get("ui_stars", 0)) >= HAPPY_MIN_STARS]
    expected_unhappy = [r for r in per_doctor if int(r.get("ui_stars", 0)) < HAPPY_MIN_STARS]

    expected_happy_sorted = sorted(
        expected_happy,
        key=lambda r: (
            -int(r.get("ui_stars", 0)),
            _last_name_key(_safe_str(r.get("display_name", ""))),
            _safe_str(r.get("display_name", "")).lower(),
            int(r.get("doctor_id", 0)),
        ),
    )
    expected_unhappy_sorted = sorted(
        expected_unhappy,
        key=lambda r: (
            int(r.get("ui_stars", 0)),
            _last_name_key(_safe_str(r.get("display_name", ""))),
            _safe_str(r.get("display_name", "")).lower(),
            int(r.get("doctor_id", 0)),
        ),
    )

    assert [int(r["doctor_id"]) for r in top_happy] == [int(r["doctor_id"]) for r in expected_happy_sorted]
    assert [int(r["doctor_id"]) for r in top_unhappy] == [int(r["doctor_id"]) for r in expected_unhappy_sorted]


def test_rankings_ui_rows_have_valid_reason_codes_and_score_matches_ui_stars(make_problem_data):
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.resident, is_head=False),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
        3: DoctorInput(id=3, role=DoctorRole.resident, is_head=False),
    }
    prefs = {
        1: PreferencesInput(doctor_id=1),
        2: PreferencesInput(doctor_id=2),
        3: PreferencesInput(doctor_id=3),
    }

    problem = make_problem_data(days=[1, 2, 3], doctors=doctors, preferences=prefs, participant_doctor_ids={1, 2, 3})

    display_names = {
        1: "Adam Zebra",
        2: "Bea Apple",
        3: "Chris Mango",
    }

    # Intentionally "edit-style" schedule (can include double shift).
    assignments = [
        {"doctor_id": 1, "day": 1, "shift_type": "onsite"},
        {"doctor_id": 1, "day": 1, "shift_type": "oncall"},  # double shift
        {"doctor_id": 2, "day": 2, "shift_type": "onsite"},
    ]

    payload = _payload(participant_ids=[1, 2, 3], assignments=assignments, display_names=display_names)
    out = compute_quality(problem=problem, payload=payload)

    rankings = out["details"]["rankings"]
    top_unhappy = list(rankings["top_unhappy"])
    top_happy = list(rankings["top_happy"])

    # Everyone must be in exactly one list
    ids_unhappy = {int(r["doctor_id"]) for r in top_unhappy}
    ids_happy = {int(r["doctor_id"]) for r in top_happy}
    assert ids_unhappy.isdisjoint(ids_happy)
    assert ids_unhappy | ids_happy == {1, 2, 3}

    per_doctor = out["details"]["per_doctor"]
    per_map = {int(r["doctor_id"]): r for r in per_doctor}

    # Ranking rows: score == per_doctor.ui_stars, reasons_codes are short + whitelisted
    for r in top_unhappy + top_happy:
        did = int(r["doctor_id"])
        assert did in per_map

        ui_stars = int(per_map[did]["ui_stars"])
        assert int(r["score"]) == ui_stars

        reasons = r.get("reasons_codes", [])
        assert isinstance(reasons, list)
        assert len(reasons) <= 3
        for code in reasons:
            assert isinstance(code, str)
            assert code in ALL_REASON_CODES


def test_rankings_partition_no_overlap_even_when_all_doctors_have_three_stars(make_problem_data, monkeypatch):
    """
    Edge-case: everyone has exactly 3 stars.
    Expectation (by partition rule):
    - top_happy is empty (since happy requires >= 4)
    - top_unhappy contains everyone
    - still no overlaps
    """
    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.resident, is_head=False),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
        3: DoctorInput(id=3, role=DoctorRole.resident, is_head=False),
        4: DoctorInput(id=4, role=DoctorRole.resident, is_head=False),
    }
    prefs = {
        1: PreferencesInput(doctor_id=1),
        2: PreferencesInput(doctor_id=2),
        3: PreferencesInput(doctor_id=3),
        4: PreferencesInput(doctor_id=4),
    }

    problem = make_problem_data(
        days=[1, 2, 3, 4],
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids={1, 2, 3, 4},
    )

    # Force UI stars to 3 for everyone (testing partition logic, not the star algorithm here).
    # We patch the function inside backend.core.diagnostics module.
    import backend.core.diagnostics as diag

    def _forced_ui_quality_for_doctor(**kwargs):
        return 3, [], {"stars": 3}

    monkeypatch.setattr(diag, "_ui_quality_for_doctor", _forced_ui_quality_for_doctor)

    display_names = {
        1: "Jan Zebra",
        2: "Ala Apple",
        3: "Ola Mango",
        4: "Ewa Berry",
    }
    payload = _payload(participant_ids=[1, 2, 3, 4], assignments=[], display_names=display_names)
    out = compute_quality(problem=problem, payload=payload)

    rankings = out["details"]["rankings"]
    top_unhappy = list(rankings["top_unhappy"])
    top_happy = list(rankings["top_happy"])

    assert len(top_happy) == 0
    assert {int(r["doctor_id"]) for r in top_unhappy} == {1, 2, 3, 4}

    ids_unhappy = {int(r["doctor_id"]) for r in top_unhappy}
    ids_happy = {int(r["doctor_id"]) for r in top_happy}
    assert ids_unhappy.isdisjoint(ids_happy)
    assert ids_unhappy | ids_happy == {1, 2, 3, 4}
