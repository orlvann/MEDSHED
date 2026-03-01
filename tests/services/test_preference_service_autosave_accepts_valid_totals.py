from backend.models.schemas.preference import PreferenceWorkingPut
from backend.routers.deps import UserCtx
from backend.services.preference_service import save_working_autosave


def test_autosave_accepts_valid_weekend_subset(db_session):
    actor = UserCtx(user_id=1, role="admin", email="admin@example.com", doctor_id=None)

    payload = PreferenceWorkingPut(
        max_onsite_total=5,
        max_onsite_weekends=2,
        target_onsite_total=4,
        target_onsite_weekends=1,
    )

    ack = save_working_autosave(year=2026, month=1, doctor_id=123, payload=payload, actor=actor)

    assert ack.doctor_id == 123
    assert ack.year == 2026
    assert ack.month == 1
    # lock_version should exist (incremented/initialized)
    assert ack.lock_version is not None
