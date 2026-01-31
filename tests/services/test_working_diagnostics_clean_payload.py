"""
Working diagnostics should be computed without being "improved" by meta.exceptions.

This test is intentionally NOT about the OUTPUT of diagnostics.
Instead, we verify what SchedulingService passes into core_diagnostics.compute_quality().

Current contract:
- SchedulingService may pass meta.exceptions through for working diagnostics.
- Core diagnostics is responsible for NOT using exceptions to improve metrics.
  (It may still project some history into details.audit, depending on target rules.)
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from backend.models.orm.schedule import ScheduleWorking
from backend.services.scheduling_service import SchedulingService


def _insert_working_with_exceptions(db, *, year: int, month: int) -> None:
    """
    Insert ScheduleWorking with meta.exceptions present.

    We include two different shapes:
    - slot marker (day + shift_type) -> typically "ignore slot" marker
    - action-style record (no day/shift_type) -> publish acceptance style
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
            "exceptions": [
                {"code": "coverage_ignored_slot", "day": 3, "shift_type": "onsite"},
                {"code": "hard_missing_coverage", "justification": "force publish example", "accepted_by_user_id": 7},
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


def test_working_diagnostics_payload_keeps_meta_exceptions(monkeypatch, db_session):
    """
    SchedulingService.get_diagnostics(target='working') currently passes payload.meta.exceptions
    through to core diagnostics.

    Why this test exists:
    - We want to lock in the CURRENT behavior to prevent accidental silent changes.
    - Other tests should verify the semantic rule: exceptions must not "improve" metrics.
      (This test only inspects the payload passed to compute_quality.)
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
                "coverage_missing_required_slots": 0,
                "hard_issues_count": 0,
                "rest_violations": 0,
                "fairness_index": 1.0,
                "preference_fulfillment_pct": 100.0,
                "penalty_total": 0,
                "understaffed_days": 0,
            },
            "details": {
                "findings": [],
                "audit": [],
                "per_doctor": [],
                "rankings": {"top_unhappy": [], "top_happy": []},
                "components": {},
            },
        }

    monkeypatch.setattr(core_diag, "compute_quality", _fake_compute_quality)

    svc = SchedulingService()
    out = svc.get_diagnostics(year=year, month=month, target="working")

    # Working diagnostics is not tied to an immutable ScheduleVersion id.
    # The UI should use details.working_lock_version for OCC workflows.
    assert out.version_id is None
    assert out.details is not None
    assert out.details.working_lock_version == 5

    payload_seen: Optional[Dict[str, Any]] = captured["payload_seen"]
    assert isinstance(payload_seen, dict)

    meta = payload_seen.get("meta") or {}
    assert isinstance(meta, dict)

    # Current behavior: exceptions are passed through (not stripped here).
    exceptions = meta.get("exceptions")
    assert isinstance(exceptions, list)

    assert exceptions == [
        {"code": "coverage_ignored_slot", "day": 3, "shift_type": "onsite"},
        {"code": "hard_missing_coverage", "justification": "force publish example", "accepted_by_user_id": 7},
    ]
