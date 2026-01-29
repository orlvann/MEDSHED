"""
Working diagnostics should be computed "clean" (ignoring meta.exceptions).

We verify it by monkeypatching core_diagnostics.compute_quality and capturing the payload
that SchedulingService passes into it.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from backend.models.orm.schedule import ScheduleWorking
from backend.services.scheduling_service import SchedulingService


def _insert_working_with_exceptions(db, *, year: int, month: int) -> None:
    """
    Insert ScheduleWorking with meta.exceptions present to test clean diagnostics behavior.
    """
    payload = {
        "participant_doctor_ids": [1],
        "assignments": [],
        "inputs_snapshot": {
            "doctors": {
                1: {
                    "role": "specialist",
                    "is_head": False,
                    "display_name": "Doc One",
                    "is_active_at_snapshot": True,
                }
            },
            "preference_version_id_by_doctor": {1: None},
        },
        "meta": {
            "labels": ["as_generated"],
            # IMPORTANT: these should be ignored by working diagnostics
            "exceptions": [
                {"code": "coverage_ignored_day", "day": 3},
                {"code": "coverage_ignored_slot", "day": 5, "shift_type": "onsite"},
            ],
            "solver_status": "OK",
        },
    }

    w = ScheduleWorking(
        year=year,
        month=month,
        payload=payload,
        lock_version=5,
        updated_by_user_id=None,
    )
    db.add(w)
    db.commit()


def test_working_diagnostics_ignores_meta_exceptions(monkeypatch, db_session):
    """
    SchedulingService.get_diagnostics(target='working') should call compute_quality()
    with a payload that does NOT include meta.exceptions.
    """
    year, month = 2026, 2
    _insert_working_with_exceptions(db_session, year=year, month=month)

    captured: Dict[str, Any] = {"payload_seen": None}

    # Patch compute_quality to capture payload argument and return a minimal valid structure.
    from backend.core import diagnostics as core_diag

    def _fake_compute_quality(*, problem, payload):
        # Store a copy so later mutations do not affect assertions.
        captured["payload_seen"] = dict(payload or {})
        return {
            "summary": {
                "score_total": 0.0,
                "coverage_gaps_total": 0,
                "hard_violations_total": 0,
            },
            "details": {},
        }

    monkeypatch.setattr(core_diag, "compute_quality", _fake_compute_quality)

    svc = SchedulingService()
    out = svc.get_diagnostics(year=year, month=month, target="working")

    assert out.version_id == "working"

    payload_seen: Optional[Dict[str, Any]] = captured["payload_seen"]
    assert isinstance(payload_seen, dict)

    meta = payload_seen.get("meta") or {}
    assert isinstance(meta, dict)

    # The key expectation: meta.exceptions must be removed (or empty).
    assert meta.get("exceptions") in (None, [], {}), "working diagnostics must ignore exceptions"
