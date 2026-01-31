from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from backend.services.scheduling_service import SchedulingService


@dataclass
class _FakeWorking:
    payload: Dict[str, Any]
    lock_version: int = 7
    updated_at: Optional[object] = None
    updated_by_user_id: Optional[int] = None


class _FakeSession:
    """
    Fake DB session used to exercise save_working() end-to-end without a real DB.
    """

    def __init__(self, working: _FakeWorking):
        self._working = working

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, model, pk):
        if getattr(model, "__name__", "") == "ScheduleWorking":
            return self._working
        return None

    def add(self, obj) -> None:
        return None

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        return None


def test_save_working_enforces_labels_and_keeps_exceptions(monkeypatch):
    """
    Policy:
    - remove "as_generated"
    - add "edited_by_admin"
    - keep other labels
    - do NOT delete meta.exceptions
    """
    svc = SchedulingService()

    exceptions = [
        {"kind": "generation_ignore", "code": "coverage_ignored_slot", "day": 2, "shift_type": "onsite"},
        {"kind": "note", "code": "anything", "custom_field": "must_survive"},
    ]

    fake_working = _FakeWorking(
        payload={
            "participant_doctor_ids": [101],
            "assignments": [],
            "meta": {"labels": ["as_generated", "foo", "bar"], "exceptions": list(exceptions)},
            "inputs_snapshot": {"doctors": {}, "preference_version_id_by_doctor": {}},
        }
    )

    from backend.services import scheduling_service as mod

    monkeypatch.setattr(mod, "SessionLocal", lambda: _FakeSession(fake_working))

    # We pass meta like FE would: labels + exceptions.
    svc.save_working(
        year=2026,
        month=2,
        assignments=[],
        meta={"labels": ["as_generated", "foo", "bar"], "exceptions": list(exceptions)},
        if_match_lock_version=7,
        updated_by_user_id=1,
    )

    # Read back what service persisted into the working payload.
    saved_meta = fake_working.payload.get("meta") or {}
    saved_labels = saved_meta.get("labels") or []
    saved_exceptions = saved_meta.get("exceptions") or []

    assert "as_generated" not in saved_labels
    assert "edited_by_admin" in saved_labels
    assert "foo" in saved_labels
    assert "bar" in saved_labels

    # Exceptions should not be dropped or trimmed.
    assert saved_exceptions == exceptions
