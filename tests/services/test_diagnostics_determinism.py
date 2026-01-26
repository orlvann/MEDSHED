# tests/services/test_diagnostics_determinism.py
"""
Determinism tests for diagnostics.

What we verify:
1) target=draft diagnostics are deterministic for a given version_id
   when payload contains inputs_snapshot.
2) target=working diagnostics are deterministic when working payload contains inputs_snapshot.

Why this matters:
- diagnostics must be computed from the SAME frozen inputs that were used at generation time,
  not from current DB state (Doctor rows / PreferencePointer changes).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import pytest

from backend.models.common_enums import DoctorRole, ShiftType
from backend.models.orm.doctor import Doctor
from backend.models.orm.preference import PreferencePointer, PreferenceVersion
from backend.models.orm.schedule import SchedulePointer, ScheduleVersion, ScheduleWorking
from backend.services.scheduling_service import SchedulingService

# Fixed timestamp used in test rows (PreferenceVersion.created_at is NOT nullable).
FIXED_TS = datetime(2026, 1, 1, 0, 0, 0)


def _mk_pref_payload(*, preferred_onsite_days: List[int]) -> Dict[str, Any]:
    """
    Build a minimal preferences payload dict.

    We only fill fields that are likely to affect diagnostics/scoring:
    - preferred_onsite_days is a simple, visible signal.
    """
    return {
        "unavailable_onsite_days": [],
        "unavailable_oncall_days": [],
        "preferred_onsite_days": list(preferred_onsite_days),
        "preferred_oncall_days": [],
        "preferred_onsite_weekdays": [],
        "preferred_oncall_weekdays": [],
        "avoid_onsite_weekdays": [],
        "avoid_oncall_weekdays": [],
        "preferred_partners": [],
        "allow_weekend_consecutive_onsite_oncall": False,
        "comments": None,
    }


def _mk_inputs_snapshot(
    *,
    doctors: Dict[int, Dict[str, Any]],
    pref_version_id_by_doctor: Dict[int, Optional[int]],
) -> Dict[str, Any]:
    """
    Create inputs_snapshot in the exact structure expected by diagnostics_service.

    Note:
    - In real JSON, keys can become strings.
      Our diagnostics_service is defensive and accepts both int and str keys.
    """
    return {
        "doctors": doctors,
        "preference_version_id_by_doctor": pref_version_id_by_doctor,
    }


def _mk_schedule_payload(
    *,
    participant_doctor_ids: List[int],
    assignments: List[Dict[str, Any]],
    inputs_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build the minimal schedule payload used by diagnostics.
    """
    return {
        "participant_doctor_ids": list(participant_doctor_ids),
        "assignments": list(assignments),
        "inputs_snapshot": dict(inputs_snapshot),
        "meta": {"labels": ["test"], "exceptions": []},
    }


@pytest.mark.usefixtures("db_session")
def test_diagnostics_draft_is_deterministic_for_version_id(db_session):
    """
    Even if DB changes after the schedule version was created,
    diagnostics for that version_id must stay the same when inputs_snapshot exists.
    """
    year = 2026
    month = 1

    # -----------------------------
    # 1) Seed doctors (DB state #1)
    # -----------------------------
    db_session.add_all(
        [
            Doctor(
                id=1,
                first_name="Alice",
                last_name="One",
                role=DoctorRole.specialist,
                is_active=True,
                is_head=False,
            ),
            Doctor(
                id=2,
                first_name="Bob",
                last_name="Two",
                role=DoctorRole.resident,
                is_active=True,
                is_head=False,
            ),
        ]
    )
    db_session.flush()

    # -----------------------------------------
    # 2) Seed preference versions + pointers #1
    # -----------------------------------------
    db_session.add_all(
        [
            PreferenceVersion(
                id=101,
                doctor_id=1,
                year=year,
                month=month,
                kind="checkpoint",
                payload=_mk_pref_payload(preferred_onsite_days=[1]),
                created_at=FIXED_TS,
                created_by_user_id=1,
                created_by_role="doctor",
                note=None,
            ),
            PreferenceVersion(
                id=102,
                doctor_id=2,
                year=year,
                month=month,
                kind="checkpoint",
                payload=_mk_pref_payload(preferred_onsite_days=[2]),
                created_at=FIXED_TS,
                created_by_user_id=1,
                created_by_role="doctor",
                note=None,
            ),
        ]
    )
    db_session.flush()

    db_session.add_all(
        [
            PreferencePointer(doctor_id=1, year=year, month=month, current_version_id=101),
            PreferencePointer(doctor_id=2, year=year, month=month, current_version_id=102),
        ]
    )
    db_session.flush()

    # -----------------------------------------
    # 3) Create schedule payload WITH snapshot
    # -----------------------------------------
    inputs_snapshot = _mk_inputs_snapshot(
        doctors={
            1: {
                "role": "specialist",
                "is_head": False,
                "display_name": "Alice One",
                "is_active_at_snapshot": True,
            },
            2: {
                "role": "resident",
                "is_head": False,
                "display_name": "Bob Two",
                "is_active_at_snapshot": True,
            },
        },
        pref_version_id_by_doctor={1: 101, 2: 102},
    )

    schedule_payload = _mk_schedule_payload(
        participant_doctor_ids=[1, 2],
        assignments=[
            {"day": 1, "shift_type": ShiftType.onsite.value, "doctor_id": 1},
            {"day": 1, "shift_type": ShiftType.oncall.value, "doctor_id": 2},
        ],
        inputs_snapshot=inputs_snapshot,
    )

    # Insert an immutable draft version and point the draft pointer to it.
    db_session.add(ScheduleVersion(id=201, year=year, month=month, kind="draft", payload=schedule_payload))
    db_session.flush()

    db_session.add(
        SchedulePointer(
            year=year,
            month=month,
            current_draft_version_id=201,
            current_published_version_id=None,
        )
    )
    db_session.flush()

    # IMPORTANT: commit, because SchedulingService opens its own SessionLocal.
    db_session.commit()

    service = SchedulingService()

    # First diagnostics result (baseline)
    diag1 = service.get_diagnostics(year, month, target="draft")
    s1 = diag1.summary.model_dump()
    d1 = diag1.details

    # -----------------------------------------
    # 4) Mutate DB state (do NOT touch version payload!)
    # -----------------------------------------
    # If diagnostics incorrectly used "current DB state", results would change.
    with db_session.begin():
        doc1_db = db_session.get(Doctor, 1)
        doc2_db = db_session.get(Doctor, 2)
        assert doc1_db is not None
        assert doc2_db is not None

        # Change doctor properties (role/head/name)
        doc1_db.role = DoctorRole.resident
        doc1_db.is_head = True
        doc1_db.first_name = "Changed"
        doc1_db.last_name = "Name"

        # Create NEW preference versions with different payloads
        db_session.add_all(
            [
                PreferenceVersion(
                    id=103,
                    doctor_id=1,
                    year=year,
                    month=month,
                    kind="checkpoint",
                    payload=_mk_pref_payload(preferred_onsite_days=[3]),
                    created_at=FIXED_TS,
                    created_by_user_id=1,
                    created_by_role="doctor",
                    note="new",
                ),
                PreferenceVersion(
                    id=104,
                    doctor_id=2,
                    year=year,
                    month=month,
                    kind="checkpoint",
                    payload=_mk_pref_payload(preferred_onsite_days=[3]),
                    created_at=FIXED_TS,
                    created_by_user_id=1,
                    created_by_role="doctor",
                    note="new",
                ),
            ]
        )
        db_session.flush()

        # Repoint pointers to NEW versions
        ptr1_db = db_session.query(PreferencePointer).filter_by(doctor_id=1, year=year, month=month).one()
        ptr2_db = db_session.query(PreferencePointer).filter_by(doctor_id=2, year=year, month=month).one()
        ptr1_db.current_version_id = 103
        ptr2_db.current_version_id = 104

    # Second diagnostics result for the SAME version id
    diag2 = service.get_diagnostics(year, month, target="draft")
    s2 = diag2.summary.model_dump()
    d2 = diag2.details

    # computed_at can change (we do NOT compare it), but summary/details must stay identical.
    assert s2 == s1
    assert d2 == d1


@pytest.mark.usefixtures("db_session")
def test_diagnostics_working_is_deterministic_when_snapshot_exists(db_session):
    """
    working diagnostics must also be deterministic if working payload contains inputs_snapshot.
    """
    year = 2026
    month = 1

    # -----------------------------
    # 1) Seed doctors
    # -----------------------------
    db_session.add_all(
        [
            Doctor(
                id=1,
                first_name="Alice",
                last_name="One",
                role=DoctorRole.specialist,
                is_active=True,
                is_head=False,
            ),
            Doctor(
                id=2,
                first_name="Bob",
                last_name="Two",
                role=DoctorRole.resident,
                is_active=True,
                is_head=False,
            ),
        ]
    )
    db_session.flush()

    # -----------------------------
    # 2) Seed preference versions + pointers
    # -----------------------------
    db_session.add_all(
        [
            PreferenceVersion(
                id=101,
                doctor_id=1,
                year=year,
                month=month,
                kind="checkpoint",
                payload=_mk_pref_payload(preferred_onsite_days=[1]),
                created_at=FIXED_TS,
                created_by_user_id=1,
                created_by_role="doctor",
                note=None,
            ),
            PreferenceVersion(
                id=102,
                doctor_id=2,
                year=year,
                month=month,
                kind="checkpoint",
                payload=_mk_pref_payload(preferred_onsite_days=[2]),
                created_at=FIXED_TS,
                created_by_user_id=1,
                created_by_role="doctor",
                note=None,
            ),
        ]
    )
    db_session.flush()

    db_session.add_all(
        [
            PreferencePointer(doctor_id=1, year=year, month=month, current_version_id=101),
            PreferencePointer(doctor_id=2, year=year, month=month, current_version_id=102),
        ]
    )
    db_session.flush()

    # -----------------------------
    # 3) Seed working payload WITH snapshot
    # -----------------------------
    inputs_snapshot = _mk_inputs_snapshot(
        doctors={
            1: {
                "role": "specialist",
                "is_head": False,
                "display_name": "Alice One",
                "is_active_at_snapshot": True,
            },
            2: {
                "role": "resident",
                "is_head": False,
                "display_name": "Bob Two",
                "is_active_at_snapshot": True,
            },
        },
        pref_version_id_by_doctor={1: 101, 2: 102},
    )

    working_payload = _mk_schedule_payload(
        participant_doctor_ids=[1, 2],
        assignments=[
            {"day": 1, "shift_type": ShiftType.onsite.value, "doctor_id": 1},
            {"day": 1, "shift_type": ShiftType.oncall.value, "doctor_id": 2},
        ],
        inputs_snapshot=inputs_snapshot,
    )

    db_session.add(ScheduleWorking(year=year, month=month, payload=working_payload, lock_version=1))
    db_session.flush()

    # IMPORTANT: commit, because SchedulingService opens its own SessionLocal.
    db_session.commit()

    service = SchedulingService()

    diag1 = service.get_diagnostics(year, month, target="working")
    s1 = diag1.summary.model_dump()
    d1 = diag1.details

    # -----------------------------
    # 4) Mutate DB state (must NOT affect working diagnostics with snapshot)
    # -----------------------------
    with db_session.begin():
        doc1 = db_session.get(Doctor, 1)
        assert doc1 is not None
        doc1.role = DoctorRole.resident
        doc1.is_head = True

        # Add a new preference version and repoint pointer
        db_session.add(
            PreferenceVersion(
                id=103,
                doctor_id=1,
                year=year,
                month=month,
                kind="checkpoint",
                payload=_mk_pref_payload(preferred_onsite_days=[3]),
                created_at=FIXED_TS,
                created_by_user_id=1,
                created_by_role="doctor",
                note="new",
            )
        )
        db_session.flush()

        ptr1 = db_session.query(PreferencePointer).filter_by(doctor_id=1, year=year, month=month).one()
        ptr1.current_version_id = 103

    diag2 = service.get_diagnostics(year, month, target="working")
    s2 = diag2.summary.model_dump()
    d2 = diag2.details

    assert s2 == s1
    assert d2 == d1
