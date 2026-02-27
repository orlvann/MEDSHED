# tests/solver/test_scoring.py
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


def test_preference_weight_for_doctor_head_multiplies_on_top_of_role():
    """
    Head multiplier multiplies ON TOP of role multiplier.
    """
    head_m = int(scoring.ROLE_WEIGHT_MILLI["head"])
    spec_m = int(scoring.ROLE_WEIGHT_MILLI[DoctorRole.specialist])
    res_m = int(scoring.ROLE_WEIGHT_MILLI[DoctorRole.resident])

    # resident head => head only (resident is 1.00x)
    assert scoring.preference_weight_for_doctor(is_head=True, role=DoctorRole.resident) == head_m / 1000.0

    # specialist head => head * specialist
    assert scoring.preference_weight_for_doctor(is_head=True, role=DoctorRole.specialist) == (
        (head_m * spec_m) / (1000.0 * 1000.0)
    )

    # sanity: not-head values match pure role multipliers
    assert scoring.preference_weight_for_doctor(is_head=False, role=DoctorRole.resident) == res_m / 1000.0
    assert scoring.preference_weight_for_doctor(is_head=False, role=DoctorRole.specialist) == spec_m / 1000.0


def test_preference_weight_for_doctor_by_role_when_not_head():
    assert scoring.preference_weight_for_doctor(is_head=False, role=DoctorRole.specialist) == (
        int(scoring.ROLE_WEIGHT_MILLI[DoctorRole.specialist]) / 1000.0
    )
    assert scoring.preference_weight_for_doctor(is_head=False, role=DoctorRole.resident) == (
        int(scoring.ROLE_WEIGHT_MILLI[DoctorRole.resident]) / 1000.0
    )


def test_rest_cross_shift_weight_by_role():
    assert scoring.rest_cross_shift_weight(role=DoctorRole.specialist) == scoring.REST_CROSS_SHIFT_SPECIALIST_WEIGHT
    assert scoring.rest_cross_shift_weight(role=DoctorRole.resident) == scoring.REST_CROSS_SHIFT_RESIDENT_WEIGHT


def test_preferred_day_miss_uses_single_base_and_role_multiplier():
    """
    Preferred day miss uses ONE shared base weight for everyone,
    and applies role/head priority via effective_weight(..., category="preferred_days").
    """
    base = int(scoring.PREF_DAY_MISS_BASE_WEIGHT)
    assert base > 0

    # resident not head => 1.00x
    w_res = scoring.effective_weight(
        base_weight=base,
        category="preferred_days",
        is_head=False,
        role=DoctorRole.resident,
    )
    assert w_res == base

    # specialist not head => scaled by role multiplier
    m_spec = scoring.role_multiplier_milli(is_head=False, role=DoctorRole.specialist)
    w_spec = scoring.effective_weight(
        base_weight=base,
        category="preferred_days",
        is_head=False,
        role=DoctorRole.specialist,
    )
    assert w_spec == int((base * m_spec + 500) // 1000)

    # head specialist => scaled by head*role multiplier
    m_head_spec = scoring.role_multiplier_milli(is_head=True, role=DoctorRole.specialist)
    w_head_spec = scoring.effective_weight(
        base_weight=base,
        category="preferred_days",
        is_head=True,
        role=DoctorRole.specialist,
    )
    assert w_head_spec == int((base * m_head_spec + 500) // 1000)


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
