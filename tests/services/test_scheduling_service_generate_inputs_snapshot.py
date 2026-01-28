# tests/services/test_scheduling_service_generate_inputs_snapshot.py

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.types import SolverStatus
from backend.models.common_enums import DoctorRole, ShiftType
from backend.models.orm.doctor import Doctor
from backend.models.schemas.schedule import ScheduleGenerateRequest
from backend.services.scheduling_service import SchedulingService


@pytest.fixture()
def db_session_and_patch_sessionlocal(monkeypatch):
    """
    Create an in-memory SQLite DB for this test and patch SessionLocal used by SchedulingService.

    Why we patch:
    - SchedulingService opens its own session via SessionLocal(), so the test must ensure
      it points to our test database (not the "real" dev DB).
    """

    # In-memory SQLite database (fast, isolated per test)
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        future=True,
    )

    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    # IMPORTANT:
    # Adjust this import if your Base lives elsewhere.
    # Common variants:
    # - from backend.models.orm.base import Base
    # - from backend.db.base import Base
    from backend.db.session import Base

    # Create all tables
    Base.metadata.create_all(bind=engine)

    # Patch the SessionLocal used INSIDE scheduling_service.py module
    import backend.services.scheduling_service as scheduling_service_module

    monkeypatch.setattr(scheduling_service_module, "SessionLocal", TestingSessionLocal)

    # Provide a session for seeding data in the test
    with TestingSessionLocal() as session:
        yield session


def _as_dict(obj: Any) -> Dict[str, Any]:
    """
    Convert inputs_snapshot to a plain dict in a defensive way.

    Why:
    - Depending on how schemas are implemented, inputs_snapshot might be:
      * a Pydantic v2 model (has model_dump),
      * a plain dict,
      * something else.
    """
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    # Last resort: try __dict__ (works for simple objects)
    return dict(getattr(obj, "__dict__", {}) or {})


def test_generate_payload_has_non_empty_inputs_snapshot(db_session_and_patch_sessionlocal, monkeypatch):
    """
    Integration test (service-level):
    After generate(), the returned payload MUST contain inputs_snapshot and it MUST NOT be empty.

    We stub the solver so the test focuses on:
    - DB reads (doctors, preference pointers)
    - building inputs_snapshot
    - saving working + creating draft version payload
    """

    session = db_session_and_patch_sessionlocal

    # --------------------------
    # 1) Seed minimal DB data
    # --------------------------
    # We need at least 1 active doctor that will be included as a participant.
    doctor = Doctor(
        id=1,
        first_name="Alice",
        last_name="Smith",
        role=DoctorRole.specialist,
        is_head=False,
        is_active=True,
    )
    session.add(doctor)
    session.commit()

    # --------------------------
    # 2) Patch gatekeeper + stub solver output
    # --------------------------
    import backend.core.scheduler as scheduler_module
    import backend.services.scheduling_service as scheduling_service_module

    # IMPORTANT:
    # This test focuses on inputs_snapshot creation and persistence,
    # not on feasibility gating. We patch the gatekeeper to always pass.
    monkeypatch.setattr(
        scheduling_service_module.core_feasibility,
        "analyze_problem",
        lambda _problem: [],
    )

    # Stub core scheduler so we don't run OR-Tools.
    # The service expects solution.status to be a SolverStatus enum and must be OK.
    def fake_generate_schedule(_problem):
        fake_solution = SimpleNamespace(status=SolverStatus.OK)

        # One assignment is enough for a valid payload shape
        fake_assignments = [
            {
                "day": 1,
                "shift_type": ShiftType.onsite,  # enum is OK; normalization handles it
                "doctor_id": 1,
            }
        ]
        return SimpleNamespace(solution=fake_solution, assignments=fake_assignments)

    monkeypatch.setattr(scheduler_module, "generate_schedule", fake_generate_schedule)

    # --------------------------
    # 3) Call the service
    # --------------------------
    svc = SchedulingService()

    req = ScheduleGenerateRequest(
        year=2026,
        month=1,
        participant_doctor_ids=[1],
        ignore_slots=[],
    )

    created = svc.generate(req, user_id=123)

    # --------------------------
    # 4) Assert: inputs_snapshot exists and is not empty
    # --------------------------
    assert created.draft.payload is not None, "Draft payload should exist after generate()"

    # Draft snapshot
    draft_payload_dict = _as_dict(created.draft.payload)
    draft_snapshot_dict = _as_dict(draft_payload_dict.get("inputs_snapshot"))

    assert draft_snapshot_dict, "inputs_snapshot must be present in draft payload after generate()"

    doctors_map = draft_snapshot_dict.get("doctors") or {}
    assert doctors_map, "inputs_snapshot.doctors must NOT be empty after generate()"

    # Keys might be strings or ints depending on JSON coercion
    assert ("1" in doctors_map) or (1 in doctors_map), "inputs_snapshot.doctors must contain doctor id=1"

    pref_map = draft_snapshot_dict.get("preference_version_id_by_doctor") or {}
    assert ("1" in pref_map) or (
        1 in pref_map
    ), "inputs_snapshot.preference_version_id_by_doctor must contain doctor id=1"

    # Working snapshot should also carry it (deterministic diagnostics/publish later)
    working_snapshot_dict = _as_dict(getattr(created.working, "inputs_snapshot", None))
    assert working_snapshot_dict, "Working should keep inputs_snapshot after generate()"

    working_doctors_map = working_snapshot_dict.get("doctors") or {}
    assert working_doctors_map, "Working inputs_snapshot.doctors must not be empty"
    assert ("1" in working_doctors_map) or (1 in working_doctors_map), "Working snapshot must contain doctor id=1"
