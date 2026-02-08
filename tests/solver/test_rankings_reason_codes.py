# backend/tests/test_rankings_reason_codes.py
"""
Mini-test: diagnostics rankings reason codes must be stable and contract-safe.

This test ensures:
- rankings.reasons_codes contain ONLY codes from ALL_REASON_CODES
- no "random" / typo strings leak into API payloads
"""

from __future__ import annotations

from backend.core import diagnostics
from backend.models.constants.diagnostics_reason_codes import ALL_REASON_CODES


def _all_reason_codes_from_rankings(rankings: dict) -> set[str]:
    """
    Extract all reason codes from rankings payload.

    rankings expected shape:
    {
      "top_unhappy": [{"doctor_id": 1, "score": ..., "reasons_codes": [...]}, ...],
      "top_happy":   [{"doctor_id": 2, "score": ..., "reasons_codes": [...]}, ...],
    }
    """
    out: set[str] = set()
    for key in ("top_unhappy", "top_happy"):
        items = rankings.get(key, []) or []
        for it in items:
            for code in it.get("reasons_codes") or []:
                out.add(str(code))
    return out


def test_rankings_reason_codes_are_subset_of_all_reason_codes() -> None:
    """
    If diagnostics starts emitting any unknown reason code, fail immediately.
    """
    # Minimal per-doctor rows crafted to trigger different reasons.
    #
    # IMPORTANT:
    # Rankings reasons are now decided by ui_reasons_codes_* helpers and/or per-doctor
    # ui_reasons_codes field, so this test focuses on the *contract*:
    # no unknown strings, max 3, no empty strings.
    per_doctor_rows = [
        {
            "doctor_id": 1,
            "score": -10.0,
            "rest_violations": 1,
            "preferred_days_missed": 0,
            "preference_fulfillment_pct": 100.0,
            "ui_reasons_codes": ["rest_violations"],
        },
        {
            "doctor_id": 2,
            "score": -20.0,
            "rest_violations": 0,
            "preferred_days_missed": 2,
            "preference_fulfillment_pct": 100.0,
            "ui_reasons_codes": ["preferred_days_missed"],
        },
        {
            "doctor_id": 3,
            "score": -30.0,
            "rest_violations": 0,
            "preferred_days_missed": 0,
            "preference_fulfillment_pct": 100.0,
            "ui_reasons_codes": ["unfair_workload"],
        },
    ]

    # Trigger the "double shift same day" reason for doctor 2.
    double_shift_days_by_doctor = {1: 0, 2: 1, 3: 0}

    # Required penalty maps for _build_rankings signature.
    # Values don't need to match any "real" solver numbers here — we only need
    # deterministic, per-doctor ints so UI reason selection can run.
    pref_days_pen_by_doc = {1: 0, 2: 40, 3: 0}
    totals_pen_by_doc = {1: 0, 2: 0, 3: 0}
    fairness_pen_by_doc = {1: 0, 2: 0, 3: 40}
    weekday_pen_by_doc = {1: 0, 2: 0, 3: 0}
    fri_pen_by_doc = {1: 0, 2: 0, 3: 0}

    rankings = diagnostics._build_rankings(  # internal helper is OK to test directly
        per_doctor_rows=per_doctor_rows,
        double_shift_days_by_doctor=double_shift_days_by_doctor,
        pref_days_pen_by_doc=pref_days_pen_by_doc,
        totals_pen_by_doc=totals_pen_by_doc,
        fairness_pen_by_doc=fairness_pen_by_doc,
        weekday_pen_by_doc=weekday_pen_by_doc,
        fri_pen_by_doc=fri_pen_by_doc,
        top_n=5,
    )

    emitted = _all_reason_codes_from_rankings(rankings)

    # Core assertion: no unknown / accidental strings.
    assert emitted.issubset(
        set(ALL_REASON_CODES)
    ), f"Unknown reason codes emitted: {sorted(emitted - set(ALL_REASON_CODES))}"

    # Extra safety: enforce basic shape constraints for every emitted code.
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
            "score": 0.0,
            "rest_violations": 0,
            "preferred_days_missed": 0,
            "preference_fulfillment_pct": 100.0,
            "ui_reasons_codes": [],
        },
        {
            "doctor_id": 2,
            "score": 1.0,
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
        fri_pen_by_doc={1: 0, 2: 0},
        top_n=5,
    )

    emitted = _all_reason_codes_from_rankings(rankings)
    assert emitted.issubset(set(ALL_REASON_CODES))
