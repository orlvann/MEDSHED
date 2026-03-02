from backend.db.session import SessionLocal
from backend.models.common_enums import DoctorRole
from backend.models.orm.doctor import Doctor
from backend.models.orm.preference import PreferenceWorking
from backend.models.schemas.preference import PreferenceWorkingPut
from backend.routers.deps import UserCtx
from backend.services.preference_service import save_working_autosave


def test_autosave_accepts_valid_weekend_subset(db_session):
    """
    This test must create the referenced Doctor in the same DB session factory
    that the service uses (SessionLocal). Otherwise FK will fail because the
    service commits in its own session, not the pytest fixture session.
    """
    actor = UserCtx(user_id=1, role="admin", email="admin@example.com", doctor_id=None)

    doctor_id = 123
    year = 2026
    month = 1

    # --- Setup in the same session factory used by the service ---
    setup_session = SessionLocal()
    try:
        existing = setup_session.get(Doctor, doctor_id)
        if existing is None:
            setup_session.add(
                Doctor(
                    id=doctor_id,  # explicit because the test uses a fixed doctor_id
                    first_name="Test",
                    last_name="Doctor",
                    role=DoctorRole.specialist,
                    is_active=True,
                    is_head=False,
                    email=None,
                    phone_number=None,
                    calendar_feed_token=None,
                )
            )
            setup_session.commit()
    finally:
        setup_session.close()

    payload = PreferenceWorkingPut(
        max_onsite_total=5,
        max_onsite_weekends=2,
        target_onsite_total=4,
        target_onsite_weekends=1,
    )

    # --- Act ---
    ack = save_working_autosave(year=year, month=month, doctor_id=doctor_id, payload=payload, actor=actor)

    # --- Assert ---
    assert ack.doctor_id == doctor_id
    assert ack.year == year
    assert ack.month == month
    assert ack.lock_version is not None

    # --- Cleanup (important: we inserted data outside pytest fixture transaction) ---
    cleanup_session = SessionLocal()
    try:
        cleanup_session.query(PreferenceWorking).filter(
            PreferenceWorking.doctor_id == doctor_id,
            PreferenceWorking.year == year,
            PreferenceWorking.month == month,
        ).delete(synchronize_session=False)

        cleanup_session.query(Doctor).filter(Doctor.id == doctor_id).delete(synchronize_session=False)
        cleanup_session.commit()
    finally:
        cleanup_session.close()
