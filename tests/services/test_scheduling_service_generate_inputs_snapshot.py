# tests/services/test_scheduling_service_generate_inputs_snapshot.py

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

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
    # 2) Stub solver output
    # --------------------------
    # We patch backend.core.scheduler.generate_schedule to return a tiny deterministic result.
    # This avoids OR-Tools and makes the test fast and stable.
    def fake_generate_schedule(problem):
        fake_solution = SimpleNamespace(status=SimpleNamespace(value="optimal"))

        # One assignment is enough for a valid payload shape
        fake_assignments = [
            {
                "day": 1,
                "shift_type": ShiftType.onsite,  # enum is OK; service normalization handles it
                "doctor_id": 1,
            }
        ]
        return SimpleNamespace(solution=fake_solution, assignments=fake_assignments)

    import backend.core.scheduler as scheduler_module

    monkeypatch.setattr(scheduler_module, "generate_schedule", fake_generate_schedule)

    # --------------------------
    # 3) Call the service
    # --------------------------
    svc = SchedulingService()

    req = ScheduleGenerateRequest(
        year=2026,
        month=1,
        participant_doctor_ids=[1],
        ignore_days=[],
        ignore_slots=[],
    )

    created = svc.generate(req, user_id=123)

    # --------------------------
    # 4) Assert: inputs_snapshot exists and is not empty
    # --------------------------
    assert created.draft.payload is not None, "Draft payload should exist after generate()"

    snapshot = created.draft.payload.inputs_snapshot
    assert snapshot is not None, "inputs_snapshot must be present in draft payload after generate()"

    # Must contain at least one doctor (non-empty snapshot)
    assert snapshot.doctors, "inputs_snapshot.doctors must NOT be empty after generate()"

    # Must include our participant doctor id
    assert 1 in snapshot.doctors, "inputs_snapshot.doctors must contain the participant doctor id"

    # Optional but useful: verify preference version map has the key (value can be None)
    assert (
        1 in snapshot.preference_version_id_by_doctor
    ), "inputs_snapshot.preference_version_id_by_doctor must contain the participant doctor id"

    # Optional extra: working should also carry the same snapshot for deterministic diagnostics/publish
    assert created.working.inputs_snapshot is not None, "Working should keep inputs_snapshot after generate()"
    assert created.working.inputs_snapshot.doctors, "Working inputs_snapshot.doctors must not be empty"
