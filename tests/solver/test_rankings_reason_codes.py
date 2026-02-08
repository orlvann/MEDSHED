# backend/tests/test_rankings_reason_codes.py
"""
Mini-test: diagnostics rankings reason codes must be stable and contract-safe.

This test ensures:
- rankings.*.reasons_codes contain ONLY codes from ALL_REASON_CODES
- no "random" / typo strings leak into API payloads
"""

from __future__ import annotations

from backend.core import diagnostics
from backend.models.constants.diagnostics_reason_codes import ALL_REASON_CODES


def _all_reason_codes_from_rankings(rankings: dict) -> set[str]:
    """
    Extract all reason codes from rankings payload.

    Current rankings expected shape:
    {
      "happy":   [{"doctor_id": 1, "score": ..., "reasons_codes": [...]}, ...],
      "unhappy": [{"doctor_id": 2, "score": ..., "reasons_codes": [...]}, ...],
    }
    """
    out: set[str] = set()
    for key in ("happy", "unhappy"):
        items = rankings.get(key, []) or []
        for it in items:
            for code in it.get("reasons_codes") or []:
                out.add(str(code))
    return out


def test_rankings_reason_codes_are_subset_of_all_reason_codes() -> None:
    """
    If diagnostics starts emitting any unknown reason code, fail immediately.
    """
    per_doctor_rows = [
        {
            "doctor_id": 1,
            "ui_stars": 3,
            "display_name": "Doc One",
            "rest_violations": 1,
            "preferred_days_missed": 0,
            "preference_fulfillment_pct": 100.0,
            "ui_reasons_codes": ["rest_violations"],
        },
        {
            "doctor_id": 2,
            "ui_stars": 3,
            "display_name": "Doc Two",
            "rest_violations": 0,
            "preferred_days_missed": 2,
            "preference_fulfillment_pct": 100.0,
            "ui_reasons_codes": ["preferred_days_missed"],
        },
        {
            "doctor_id": 3,
            "ui_stars": 5,
            "display_name": "Doc Three",
            "rest_violations": 0,
            "preferred_days_missed": 0,
            "preference_fulfillment_pct": 100.0,
            # Intentionally unknown -> should be filtered out by _build_rankings validation
            "ui_reasons_codes": ["unfair_workload"],
        },
    ]

    double_shift_days_by_doctor = {1: 0, 2: 1, 3: 0}

    pref_days_pen_by_doc = {1: 0, 2: 40, 3: 0}
    totals_pen_by_doc = {1: 0, 2: 0, 3: 0}
    fairness_pen_by_doc = {1: 0, 2: 0, 3: 40}
    weekday_pen_by_doc = {1: 0, 2: 0, 3: 0}
    weekday_bonus_by_doc = {1: 0, 2: 0, 3: 0}
    fri_pen_by_doc = {1: 0, 2: 0, 3: 0}

    # New required maps (doctor_id -> bool)
    weekday_preferred_declared_by_doc = {1: False, 2: False, 3: False}
    weekday_avoid_declared_by_doc = {1: False, 2: False, 3: False}

    rankings = diagnostics._build_rankings(  # internal helper is OK to test directly
        per_doctor_rows=per_doctor_rows,
        double_shift_days_by_doctor=double_shift_days_by_doctor,
        pref_days_pen_by_doc=pref_days_pen_by_doc,
        totals_pen_by_doc=totals_pen_by_doc,
        fairness_pen_by_doc=fairness_pen_by_doc,
        weekday_pen_by_doc=weekday_pen_by_doc,
        weekday_bonus_by_doc=weekday_bonus_by_doc,
        weekday_preferred_declared_by_doc=weekday_preferred_declared_by_doc,
        weekday_avoid_declared_by_doc=weekday_avoid_declared_by_doc,
        fri_pen_by_doc=fri_pen_by_doc,
    )

    emitted = _all_reason_codes_from_rankings(rankings)

    assert emitted.issubset(
        set(ALL_REASON_CODES)
    ), f"Unknown reason codes emitted: {sorted(emitted - set(ALL_REASON_CODES))}"

    for code in emitted:
        assert isinstance(code, str)
        assert code.strip()
        assert code in ALL_REASON_CODES


def test_rankings_reason_codes_empty_is_ok() -> None:
    """
    Defensive: if rankings have no reasons (e.g., perfect schedule), it is still valid.
    """
    per_doctor_rows = [
        {
            "doctor_id": 1,
            "ui_stars": 5,
            "display_name": "Doc One",
            "rest_violations": 0,
            "preferred_days_missed": 0,
            "preference_fulfillment_pct": 100.0,
            "ui_reasons_codes": [],
        },
        {
            "doctor_id": 2,
            "ui_stars": 5,
            "display_name": "Doc Two",
            "rest_violations": 0,
            "preferred_days_missed": 0,
            "preference_fulfillment_pct": 100.0,
            "ui_reasons_codes": [],
        },
    ]

    rankings = diagnostics._build_rankings(
        per_doctor_rows=per_doctor_rows,
        double_shift_days_by_doctor={1: 0, 2: 0},
        pref_days_pen_by_doc={1: 0, 2: 0},
        totals_pen_by_doc={1: 0, 2: 0},
        fairness_pen_by_doc={1: 0, 2: 0},
        weekday_pen_by_doc={1: 0, 2: 0},
        weekday_bonus_by_doc={1: 0, 2: 0},
        weekday_preferred_declared_by_doc={1: False, 2: False},
        weekday_avoid_declared_by_doc={1: False, 2: False},
        fri_pen_by_doc={1: 0, 2: 0},
    )

    emitted = _all_reason_codes_from_rankings(rankings)
    assert emitted.issubset(set(ALL_REASON_CODES))
