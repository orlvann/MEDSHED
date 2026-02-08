from backend.core.diagnostics import _build_rankings, _ui_quality_for_doctor
from backend.models.constants.diagnostics_reason_codes import ALL_REASON_CODES


def test_ui_quality_stars_are_clamped_to_1_5():
    stars, reasons, comp = _ui_quality_for_doctor(
        doctor_id=1,
        rest_violations=999,
        preferred_days_missed=999,
        preference_fulfillment_pct=0.0,
        double_shift_days=999,
        rest_pen=999999,
        pref_days_pen=999999,
        totals_pen=999999,
        fairness_pen=999999,
        weekday_pen=999999,
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
        preference_fulfillment_pct=100.0,
        double_shift_days=1,
        rest_pen=0,
        pref_days_pen=0,
        totals_pen=0,
        fairness_pen=0,
        weekday_pen=0,
        friday_pen=0,
        partners_bonus=0.0,
    )

    assert stars <= 3  # double shift drops stars by 2
    assert "hard_double_shift_same_day" in reasons


def test_ui_quality_partners_bonus_can_add_star_back():
    # Base: make it "bad enough" that bonus can bring it up by +1.
    stars_no_bonus, _, _ = _ui_quality_for_doctor(
        doctor_id=1,
        rest_violations=1,
        preferred_days_missed=1,
        preference_fulfillment_pct=70.0,
        double_shift_days=0,
        rest_pen=50,
        pref_days_pen=20,
        totals_pen=0,
        fairness_pen=0,
        weekday_pen=0,
        friday_pen=0,
        partners_bonus=0.0,
    )

    stars_with_bonus, _, _ = _ui_quality_for_doctor(
        doctor_id=1,
        rest_violations=1,
        preferred_days_missed=1,
        preference_fulfillment_pct=70.0,
        double_shift_days=0,
        rest_pen=50,
        pref_days_pen=20,
        totals_pen=0,
        fairness_pen=0,
        weekday_pen=0,
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
        preference_fulfillment_pct=50.0,
        double_shift_days=2,
        rest_pen=1000,
        pref_days_pen=1000,
        totals_pen=1000,
        fairness_pen=1000,
        weekday_pen=1000,
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
        },
        {
            "doctor_id": 2,
            "score": 50.0,
            "rest_violations": 0,
            "preferred_days_missed": 0,
            "preference_fulfillment_pct": 95.0,
            "ui_reasons_codes": [],
        },
        {
            "doctor_id": 3,
            "score": -10.0,
            "rest_violations": 0,
            "preferred_days_missed": 0,
            "preference_fulfillment_pct": 100.0,
            "ui_reasons_codes": ["unfair_workload"],
        },
    ]

    # Provide minimal penalty maps required by _build_rankings signature.
    # Values here are intentionally simple/stable: we only test "shape + whitelist".
    pref_days_pen_by_doc = {1: 40, 2: 0, 3: 0}
    totals_pen_by_doc = {1: 0, 2: 0, 3: 0}
    fairness_pen_by_doc = {1: 0, 2: 0, 3: 20}
    weekday_pen_by_doc = {1: 0, 2: 0, 3: 0}
    fri_pen_by_doc = {1: 0, 2: 0, 3: 0}

    rankings = _build_rankings(
        per_doctor_rows=per_doctor,
        double_shift_days_by_doctor={1: 0, 2: 0, 3: 0},
        pref_days_pen_by_doc=pref_days_pen_by_doc,
        totals_pen_by_doc=totals_pen_by_doc,
        fairness_pen_by_doc=fairness_pen_by_doc,
        weekday_pen_by_doc=weekday_pen_by_doc,
        fri_pen_by_doc=fri_pen_by_doc,
        top_n=2,
    )

    assert "top_unhappy" in rankings
    assert "top_happy" in rankings

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

    _assert_rank_items(rankings["top_unhappy"])
    _assert_rank_items(rankings["top_happy"])
