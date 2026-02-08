# tests/solver/test_diagnostics_ui_quality.py
"""
Core diagnostics — UI quality (stars + reasons) and rankings reason-code hygiene.

What we test here:
- ui_stars are clamped to 1..5
- double shift is a strong penalty and produces the expected reason code
- partners bonus can increase stars (but still clamped)
- reasons list is max 3 and contains non-empty strings
- rankings reasons_codes are whitelisted and short (<=3, no duplicates)
"""

from __future__ import annotations

from backend.core.diagnostics import _build_rankings, _ui_quality_for_doctor
from backend.models.constants.diagnostics_reason_codes import (
    ALL_REASON_CODES,
    REASON_HARD_DOUBLE_SHIFT_SAME_DAY,
)


def test_ui_quality_stars_are_clamped_to_1_5():
    stars, reasons, comp = _ui_quality_for_doctor(
        doctor_id=1,
        rest_violations=999,
        preferred_days_missed=999,
        preferred_days_requested=0,
        preference_fulfillment_pct=0.0,
        double_shift_days=0,
        rest_pen=999999,
        pref_days_pen=999999,
        totals_pen=999999,
        fairness_pen=999999,
        weekday_pen=999999,
        weekday_bonus=0,  # NEW required arg
        friday_pen=999999,
        partners_bonus=0.0,
    )

    assert isinstance(stars, int)
    assert 1 <= stars <= 5
    assert isinstance(reasons, list)
    assert isinstance(comp, dict)


def test_ui_quality_double_shift_is_a_strong_penalty_and_reason_present():
    stars, reasons, _ = _ui_quality_for_doctor(
        doctor_id=1,
        rest_violations=0,
        preferred_days_missed=0,
        preferred_days_requested=0,
        preference_fulfillment_pct=100.0,
        double_shift_days=1,  # IMPORTANT: triggers the strong penalty + reason
        rest_pen=0,
        pref_days_pen=0,
        totals_pen=0,
        fairness_pen=0,
        weekday_pen=0,
        weekday_bonus=0,  # NEW required arg
        friday_pen=0,
        partners_bonus=0.0,
    )

    assert stars <= 3  # double shift drops stars by 2
    assert REASON_HARD_DOUBLE_SHIFT_SAME_DAY in reasons


def test_ui_quality_partners_bonus_can_add_star_back():
    stars_no_bonus, _, _ = _ui_quality_for_doctor(
        doctor_id=1,
        rest_violations=1,
        preferred_days_missed=1,
        preferred_days_requested=1,
        preference_fulfillment_pct=70.0,
        double_shift_days=0,
        rest_pen=50,
        pref_days_pen=20,
        totals_pen=0,
        fairness_pen=0,
        weekday_pen=0,
        weekday_bonus=0,  # NEW required arg
        friday_pen=0,
        partners_bonus=0.0,
    )

    stars_with_bonus, _, _ = _ui_quality_for_doctor(
        doctor_id=1,
        rest_violations=1,
        preferred_days_missed=1,
        preferred_days_requested=1,  # keep consistent with missed=1
        preference_fulfillment_pct=70.0,
        double_shift_days=0,
        rest_pen=50,
        pref_days_pen=20,
        totals_pen=0,
        fairness_pen=0,
        weekday_pen=0,
        weekday_bonus=0,  # NEW required arg
        friday_pen=0,
        partners_bonus=-4.0,  # strong bonus
    )

    assert stars_with_bonus >= stars_no_bonus
    assert 1 <= stars_with_bonus <= 5


def test_ui_quality_reasons_are_max_three_and_strings():
    stars, reasons, _ = _ui_quality_for_doctor(
        doctor_id=1,
        rest_violations=2,
        preferred_days_missed=5,
        preferred_days_requested=5,
        preference_fulfillment_pct=50.0,
        double_shift_days=0,
        rest_pen=1000,
        pref_days_pen=1000,
        totals_pen=1000,
        fairness_pen=1000,
        weekday_pen=1000,
        weekday_bonus=0,  # NEW required arg
        friday_pen=1000,
        partners_bonus=0.0,
    )

    assert 1 <= stars <= 5
    assert len(reasons) <= 3
    assert all(isinstance(x, str) and x.strip() for x in reasons)


def test_build_rankings_reason_codes_are_whitelisted_and_short():
    per_doctor = [
        {
            "doctor_id": 1,
            "score": -100.0,
            "rest_violations": 1,
            "preferred_days_missed": 2,
            "preference_fulfillment_pct": 70.0,
            "ui_reasons_codes": ["rest_violations", "preferred_days_missed"],
            "ui_stars": 2,
            "display_name": "Doc One",
        },
        {
            "doctor_id": 2,
            "score": 50.0,
            "rest_violations": 0,
            "preferred_days_missed": 0,
            "preference_fulfillment_pct": 95.0,
            "ui_reasons_codes": [],
            "ui_stars": 5,
            "display_name": "Doc Two",
        },
        {
            "doctor_id": 3,
            "score": -10.0,
            "rest_violations": 0,
            "preferred_days_missed": 0,
            "preference_fulfillment_pct": 100.0,
            "ui_reasons_codes": ["unfair_workload"],
            "ui_stars": 3,
            "display_name": "Doc Three",
        },
    ]

    pref_days_pen_by_doc = {1: 40, 2: 0, 3: 0}
    totals_pen_by_doc = {1: 0, 2: 0, 3: 0}
    fairness_pen_by_doc = {1: 0, 2: 0, 3: 20}

    weekday_pen_by_doc = {1: 0, 2: 0, 3: 0}
    weekday_bonus_by_doc = {1: 0, 2: 0, 3: 0}

    # NEW: "declared" flags required by _build_rankings signature
    weekday_preferred_declared_by_doc = {1: False, 2: False, 3: False}
    weekday_avoid_declared_by_doc = {1: False, 2: False, 3: False}

    fri_pen_by_doc = {1: 0, 2: 0, 3: 0}

    rankings = _build_rankings(
        per_doctor_rows=per_doctor,
        double_shift_days_by_doctor={1: 0, 2: 0, 3: 0},
        pref_days_pen_by_doc=pref_days_pen_by_doc,
        totals_pen_by_doc=totals_pen_by_doc,
        fairness_pen_by_doc=fairness_pen_by_doc,
        weekday_pen_by_doc=weekday_pen_by_doc,
        weekday_bonus_by_doc=weekday_bonus_by_doc,
        weekday_preferred_declared_by_doc=weekday_preferred_declared_by_doc,
        weekday_avoid_declared_by_doc=weekday_avoid_declared_by_doc,
        fri_pen_by_doc=fri_pen_by_doc,
    )

    assert "unhappy" in rankings
    assert "happy" in rankings

    def _assert_rank_items(items):
        assert isinstance(items, list)
        for it in items:
            assert isinstance(it, dict)

            codes = it.get("reasons_codes", [])
            assert isinstance(codes, list)
            assert len(codes) <= 3
            assert len(set(codes)) == len(codes)  # no duplicates

            for c in codes:
                assert isinstance(c, str)
                assert c.strip()
                assert c in ALL_REASON_CODES

    _assert_rank_items(rankings["unhappy"])
    _assert_rank_items(rankings["happy"])
