from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import pytest

from backend.services.errors import DomainError
from backend.services.scheduling_service import SchedulingService


@dataclass
class _FakeWorking:
    payload: Dict[str, Any]
    lock_version: int = 1
    updated_at: Optional[object] = None


class _FakeSession:
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

    def commit(self) -> None:
        return None


def test_working_diagnostics_without_inputs_snapshot_raises_domain_error(monkeypatch):
    """
    Policy: working diagnostics MUST fail if working payload has no inputs_snapshot.
    """
    svc = SchedulingService()

    fake_working = _FakeWorking(
        payload={
            "participant_doctor_ids": [101],
            "assignments": [],
            "meta": {"labels": ["edited_by_admin"], "exceptions": []},
            # inputs_snapshot missing
        }
    )

    from backend.services import scheduling_service as mod

    monkeypatch.setattr(mod, "SessionLocal", lambda: _FakeSession(fake_working))

    with pytest.raises(DomainError) as ex:
        svc.get_diagnostics(year=2026, month=2, target="working")

    assert getattr(ex.value, "code", str(ex.value)) == "working_requires_snapshot"
