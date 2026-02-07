# tests/core/test_rest_window.py

from backend.core.rest_window import rest_violation_kind
from backend.models.common_enums import ShiftType


def test_onsite_onsite_is_violation():
    assert (
        rest_violation_kind(
            prev_shift=ShiftType.onsite,
            next_shift=ShiftType.onsite,
            is_weekend_pair=False,
            allow_weekend_consecutive=False,
        )
        == "onsite_onsite"
    )


def test_oncall_oncall_is_violation():
    assert (
        rest_violation_kind(
            prev_shift=ShiftType.oncall,
            next_shift=ShiftType.oncall,
            is_weekend_pair=False,
            allow_weekend_consecutive=False,
        )
        == "oncall_oncall"
    )


def test_cross_is_violation_on_weekday_even_if_flag_true():
    assert (
        rest_violation_kind(
            prev_shift=ShiftType.onsite,
            next_shift=ShiftType.oncall,
            is_weekend_pair=False,
            allow_weekend_consecutive=True,
        )
        == "cross"
    )


def test_cross_is_allowed_on_sat_to_sun_when_flag_true():
    assert (
        rest_violation_kind(
            prev_shift=ShiftType.onsite,
            next_shift=ShiftType.oncall,
            is_weekend_pair=True,
            allow_weekend_consecutive=True,
        )
        is None
    )


def test_cross_is_violation_on_sat_to_sun_when_flag_false():
    assert (
        rest_violation_kind(
            prev_shift=ShiftType.oncall,
            next_shift=ShiftType.onsite,
            is_weekend_pair=True,
            allow_weekend_consecutive=False,
        )
        == "cross"
    )
