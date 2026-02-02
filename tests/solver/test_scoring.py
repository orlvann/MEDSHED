# tests/core/test_scoring.py
"""
Unit tests for backend/core/scoring.py.

Goal:
- Freeze weight constants and mappings.
- Ensure helper functions return expected values for all cases.

These tests are intentionally simple and deterministic.
"""

import pytest

from backend.core import scoring
from backend.models.common_enums import DoctorRole, ShiftType


def test_preference_weight_for_doctor_head_is_highest():
    # Head should always return the dedicated "head" multiplier, regardless of role.
    assert (
        scoring.preference_weight_for_doctor(is_head=True, role=DoctorRole.resident)
        == scoring.ROLE_PREFERENCE_WEIGHTS["head"]
    )
    assert (
        scoring.preference_weight_for_doctor(is_head=True, role=DoctorRole.specialist)
        == scoring.ROLE_PREFERENCE_WEIGHTS["head"]
    )


def test_preference_weight_for_doctor_by_role_when_not_head():
    assert (
        scoring.preference_weight_for_doctor(is_head=False, role=DoctorRole.specialist)
        == scoring.ROLE_PREFERENCE_WEIGHTS[DoctorRole.specialist]
    )
    assert (
        scoring.preference_weight_for_doctor(is_head=False, role=DoctorRole.resident)
        == scoring.ROLE_PREFERENCE_WEIGHTS[DoctorRole.resident]
    )


def test_rest_cross_shift_weight_by_role():
    assert scoring.rest_cross_shift_weight(role=DoctorRole.specialist) == scoring.REST_CROSS_SHIFT_SPECIALIST_WEIGHT
    assert scoring.rest_cross_shift_weight(role=DoctorRole.resident) == scoring.REST_CROSS_SHIFT_RESIDENT_WEIGHT


def test_preferred_day_miss_weight_sums_head_plus_role():
    # Resident, not head
    assert (
        scoring.preferred_day_miss_weight_for_doctor(is_head=False, role=DoctorRole.resident)
        == scoring.PREF_DAY_RESIDENT_MISS_WEIGHT
    )

    # Specialist, not head
    assert (
        scoring.preferred_day_miss_weight_for_doctor(is_head=False, role=DoctorRole.specialist)
        == scoring.PREF_DAY_SPECIALIST_MISS_WEIGHT
    )

    # Resident + head -> sum
    assert scoring.preferred_day_miss_weight_for_doctor(is_head=True, role=DoctorRole.resident) == (
        scoring.PREF_DAY_RESIDENT_MISS_WEIGHT + scoring.PREF_DAY_HEAD_MISS_WEIGHT
    )

    # Specialist + head -> sum
    assert scoring.preferred_day_miss_weight_for_doctor(is_head=True, role=DoctorRole.specialist) == (
        scoring.PREF_DAY_SPECIALIST_MISS_WEIGHT + scoring.PREF_DAY_HEAD_MISS_WEIGHT
    )


def test_fairness_weight_mapping():
    assert (
        scoring.fairness_weight(shift_type=ShiftType.onsite, is_weekend=False) == scoring.FAIRNESS_WEEKDAY_ONSITE_WEIGHT
    )
    assert (
        scoring.fairness_weight(shift_type=ShiftType.onsite, is_weekend=True) == scoring.FAIRNESS_WEEKEND_ONSITE_WEIGHT
    )
    assert (
        scoring.fairness_weight(shift_type=ShiftType.oncall, is_weekend=False) == scoring.FAIRNESS_WEEKDAY_ONCALL_WEIGHT
    )
    assert (
        scoring.fairness_weight(shift_type=ShiftType.oncall, is_weekend=True) == scoring.FAIRNESS_WEEKEND_ONCALL_WEIGHT
    )


def test_weekday_pattern_weight_preferred_and_avoid():
    assert scoring.weekday_pattern_weight(kind="preferred") == scoring.WEEKDAY_PREFERRED_BONUS_WEIGHT
    assert scoring.weekday_pattern_weight(kind="avoid") == scoring.WEEKDAY_AVOID_PENALTY_WEIGHT


def test_weekday_pattern_weight_unknown_kind_raises():
    with pytest.raises(ValueError):
        scoring.weekday_pattern_weight(kind="something_else")


def test_preferred_partner_bonus_weight():
    assert scoring.preferred_partner_bonus_weight() == scoring.PREFERRED_PARTNER_BONUS_WEIGHT
    assert isinstance(scoring.preferred_partner_bonus_weight(), int)


def test_friday_with_free_weekend_weight():
    assert scoring.friday_with_free_weekend_weight() == scoring.FRIDAY_WITH_FREE_WEEKEND_WEIGHT
    assert isinstance(scoring.friday_with_free_weekend_weight(), int)
