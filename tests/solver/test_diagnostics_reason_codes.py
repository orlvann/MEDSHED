# tests/solver/test_diagnostics_reason_codes.py

from __future__ import annotations

from backend.core.diagnostics import _build_rankings, ui_reasons_codes_happy, ui_reasons_codes_unhappy
from backend.models.constants.diagnostics_reason_codes import (
    ALL_REASON_CODES,
    REASON_BALANCED_LOAD,
    REASON_FRIDAY_PENALTY,
    REASON_GOOD_REST,
    REASON_HARD_DOUBLE_SHIFT_SAME_DAY,
    REASON_OVERLOADED_TOTALS,
    REASON_PREFERENCES_MET,
    REASON_PREFERENCES_NOT_FULLY_MET,
    REASON_REST_VIOLATIONS,
    REASON_WEEKDAY_AVOID_HIT,
)


def _assert_subset(codes: list[str]) -> None:
    for c in codes:
        assert c in ALL_REASON_CODES, f"Unknown reason code emitted: {c!r}"


def test_ui_reasons_codes_unhappy_subset_of_all_reason_codes() -> None:
    row = {
        "doctor_id": 1,
        "rest_violations": 1,
        "preferred_days_missed": 0,
        "preference_fulfillment_pct": 99.0,
        "score": -10.0,
    }

    reasons = ui_reasons_codes_unhappy(
        row=row,
        double_shift_days_by_doctor={1: 1},
        pref_days_pen_by_doc={1: 0},
        totals_pen_by_doc={1: 100},  # dominant
        fairness_pen_by_doc={1: 0},
        weekday_pen_by_doc={1: 0},
        fri_pen_by_doc={1: 0},
    )

    _assert_subset(reasons)
    # Covers multiple codes in one go (and ensures we don't emit random strings)
    assert REASON_REST_VIOLATIONS in reasons
    assert REASON_HARD_DOUBLE_SHIFT_SAME_DAY in reasons
    assert REASON_OVERLOADED_TOTALS in reasons


def test_ui_reasons_codes_unhappy_weekday_avoid_hit_when_dominant() -> None:
    """
    With the new weekday model:
    - weekday_pen_by_doc is the "avoid weekdays hit" penalty (>= 0)
    so a dominant weekday penalty should emit REASON_WEEKDAY_AVOID_HIT.
    """
    row = {
        "doctor_id": 2,
        "rest_violations": 0,
        "preferred_days_missed": 0,
        "preference_fulfillment_pct": 100.0,
        "score": -5.0,
    }

    reasons = ui_reasons_codes_unhappy(
        row=row,
        double_shift_days_by_doctor={2: 0},
        pref_days_pen_by_doc={2: 0},
        totals_pen_by_doc={2: 0},
        fairness_pen_by_doc={2: 0},
        weekday_pen_by_doc={2: 80},  # dominant weekday avoid penalty
        fri_pen_by_doc={2: 0},
    )

    _assert_subset(reasons)
    assert REASON_WEEKDAY_AVOID_HIT in reasons


def test_ui_reasons_codes_unhappy_friday_penalty_when_dominant() -> None:
    row = {
        "doctor_id": 3,
        "rest_violations": 0,
        "preferred_days_missed": 0,
        "preference_fulfillment_pct": 100.0,
        "score": -2.0,
    }

    reasons = ui_reasons_codes_unhappy(
        row=row,
        double_shift_days_by_doctor={3: 0},
        pref_days_pen_by_doc={3: 0},
        totals_pen_by_doc={3: 0},
        fairness_pen_by_doc={3: 0},
        weekday_pen_by_doc={3: 0},
        fri_pen_by_doc={3: 50},  # dominant
    )

    _assert_subset(reasons)
    assert REASON_FRIDAY_PENALTY in reasons


def test_ui_reasons_codes_unhappy_fallback_preferences_not_fully_met_only_when_needed() -> None:
    row = {
        "doctor_id": 4,
        "rest_violations": 0,
        "preferred_days_missed": 0,
        "preference_fulfillment_pct": 90.0,
        "score": -1.0,
    }

    # Soft penalties exist, but none of mapped components are > 0 (fairness-only case).
    reasons = ui_reasons_codes_unhappy(
        row=row,
        double_shift_days_by_doctor={4: 0},
        pref_days_pen_by_doc={4: 0},
        totals_pen_by_doc={4: 0},
        fairness_pen_by_doc={4: 10},  # fairness-only
        weekday_pen_by_doc={4: 0},
        fri_pen_by_doc={4: 0},
    )

    _assert_subset(reasons)
    assert reasons == [REASON_PREFERENCES_NOT_FULLY_MET]


def test_ui_reasons_codes_happy_subset_and_balanced_load() -> None:
    row = {
        "doctor_id": 10,
        "rest_violations": 0,
        "preference_fulfillment_pct": 95.0,
        "score": 5.0,
    }

    reasons = ui_reasons_codes_happy(
        row=row,
        totals_pen_by_doc={10: 0},
        fairness_pen_by_doc={10: 0},
    )

    _assert_subset(reasons)
    assert REASON_GOOD_REST in reasons
    assert REASON_PREFERENCES_MET in reasons
    assert REASON_BALANCED_LOAD in reasons


def test_build_rankings_emits_only_known_reason_codes() -> None:
    per_doctor_rows = [
        {
            "doctor_id": 1,
            "ui_stars": 2,
            "display_name": "Doc One",
            "rest_violations": 1,
            "preference_fulfillment_pct": 99.0,
        },
        {
            "doctor_id": 2,
            "ui_stars": 3,
            "display_name": "Doc Two",
            "rest_violations": 0,
            "preference_fulfillment_pct": 100.0,
        },
        {
            "doctor_id": 3,
            "ui_stars": 5,
            "display_name": "Doc Three",
            "rest_violations": 0,
            "preference_fulfillment_pct": 90.0,
        },
    ]

    rankings = _build_rankings(
        per_doctor_rows=per_doctor_rows,
        double_shift_days_by_doctor={1: 1, 2: 0, 3: 0},
        pref_days_pen_by_doc={1: 0, 2: 30, 3: 0},
        totals_pen_by_doc={1: 100, 2: 0, 3: 0},
        fairness_pen_by_doc={1: 0, 2: 0, 3: 0},
        weekday_pen_by_doc={1: 0, 2: 0, 3: 0},
        weekday_bonus_by_doc={1: 0, 2: 0, 3: 0},
        weekday_preferred_declared_by_doc={1: False, 2: False, 3: False},
        weekday_avoid_declared_by_doc={1: False, 2: False, 3: False},
        fri_pen_by_doc={1: 0, 2: 0, 3: 0},
    )

    for item in rankings.get("unhappy", []):
        _assert_subset(item.get("reasons_codes", []))

    for item in rankings.get("happy", []):
        _assert_subset(item.get("reasons_codes", []))
