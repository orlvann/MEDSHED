import pytest
from pydantic import ValidationError

from backend.models.schemas.preference import PreferenceWorkingPut


def test_max_weekends_cannot_exceed_max_total():
    with pytest.raises(ValidationError) as exc:
        PreferenceWorkingPut(max_onsite_total=2, max_onsite_weekends=5)

    # Optional: check that the message is user-facing and points to the rule
    msg = str(exc.value)
    assert "max_onsite_weekends" in msg
    assert "max_onsite_total" in msg


def test_target_weekends_cannot_exceed_target_total():
    with pytest.raises(ValidationError) as exc:
        PreferenceWorkingPut(target_onsite_total=1, target_onsite_weekends=2)

    msg = str(exc.value)
    assert "target_onsite_weekends" in msg
    assert "target_onsite_total" in msg
