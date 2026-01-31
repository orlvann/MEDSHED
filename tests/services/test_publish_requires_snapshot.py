from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import pytest

from backend.services.errors import DomainError
from backend.services.scheduling_service import SchedulingService


@dataclass
class _FakeWorking:
    """
    Minimal working ORM-like object used by SchedulingService.
    We only implement fields that the service touches.
    """

    payload: Dict[str, Any]
    lock_version: int = 1
    updated_at: Optional[object] = None
    updated_by_user_id: Optional[int] = None


class _FakeSession:
    """
    Minimal Session-like object to satisfy code paths up to the snapshot check.
    """

    def __init__(self, working: _FakeWorking):
        self._working = working

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, model, pk):
        # Service calls session.get(ScheduleWorking, {"year":..., "month":...})
        if getattr(model, "__name__", "") == "ScheduleWorking":
            return self._working
        return None

    def add(self, obj) -> None:
        return None

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        return None


def test_publish_without_inputs_snapshot_raises_domain_error(monkeypatch):
    """
    Policy: publish MUST fail if working payload has no inputs_snapshot.
    """
    svc = SchedulingService()

    fake_working = _FakeWorking(
        payload={
            "participant_doctor_ids": [101],
            "assignments": [],
            "meta": {"labels": ["as_generated"], "exceptions": []},
            # IMPORTANT: inputs_snapshot is missing on purpose
        }
    )

    # Patch SessionLocal() used inside SchedulingService to our fake context manager.
    from backend.services import scheduling_service as mod

    monkeypatch.setattr(mod, "SessionLocal", lambda: _FakeSession(fake_working))

    with pytest.raises(DomainError) as ex:
        svc.publish(year=2026, month=2, force=False, accepted_exceptions=None, note=None, user_id=1)

    # DomainError exposes .code (and is also a ValueError).
    assert getattr(ex.value, "code", str(ex.value)) == "publish_requires_snapshot"
