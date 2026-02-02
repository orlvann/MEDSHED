"""
Availability service tests (heatmap + drilldown).

What we verify:
- risk is ONLY ok / critical (no alert).
- risk_issues come ONLY from backend/core/issues.classify_feasibility_issues_for_day
  via classify_availability_risk_with_reasons (single source of truth).
- availability_service does NOT "invent" extra codes (e.g. forced_double_shift_same_day)
  on top of the core classifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Set, Tuple

import pytest

from backend.core.issues import NO_ONCALL_CANDIDATE, NO_ONSITE_CANDIDATE, NO_SPECIALIST
from backend.models.common_enums import DoctorRole, RiskLevel
from backend.services import availability_service

pytestmark = [pytest.mark.services]


@dataclass
class _FakeDoctor:
    id: int
    role: DoctorRole
    first_name: str = "A"
    last_name: str = "B"
    is_active: bool = True


class _FakeQuery:
    def __init__(self, items):
        self._items = list(items)

    def filter_by(self, **kwargs):
        return self

    def all(self):
        return list(self._items)


class _FakeSession:
    def __init__(self, doctors: List[_FakeDoctor]):
        self._doctors = list(doctors)

    def query(self, model):
        # availability_service queries only Doctor in these tests
        return _FakeQuery(self._doctors)


class _FakeSessionLocal:
    """
    Acts like SessionLocal() used as a context manager:
    with SessionLocal() as session:
        ...
    """

    def __init__(self, doctors: List[_FakeDoctor]):
        self._session = _FakeSession(doctors)

    def __call__(self):
        return self

    def __enter__(self):
        return self._session

    def __exit__(self, exc_type, exc, tb):
        return False


def test_month_availability_heatmap_returns_only_ok_or_critical_and_core_issue_codes(monkeypatch):
    """
    Day 1: both shifts have candidates and at least one specialist => ok, issues=[]
    Day 2: no candidates for both shifts => critical, issues=[NO_ONSITE_CANDIDATE, NO_ONCALL_CANDIDATE, NO_SPECIALIST]
    """
    # Make a stable "2-day month"
    monkeypatch.setattr(availability_service, "days_in_month", lambda year, month: 2)

    # Avoid touching real checkpoints / DB
    monkeypatch.setattr(availability_service, "ensure_latest_checkpoints_for_period", lambda **kwargs: None)

    # Stable period status (does not matter for risk assertions)
    monkeypatch.setattr(availability_service, "get_period_status", lambda year, month: "future")

    # Fake active doctors
    doctors = [
        _FakeDoctor(id=1, role=DoctorRole.specialist, first_name="Spec", last_name="One"),
        _FakeDoctor(id=2, role=DoctorRole.resident, first_name="Res", last_name="Two"),
    ]
    monkeypatch.setattr(availability_service, "SessionLocal", _FakeSessionLocal(doctors))

    # Control availability without Preferences/ORM:
    # - both doctors available only on day=1 for both categories
    def _fake_compute_available_days_for_doctor(*args, **kwargs) -> Tuple[Set[int], Set[int]]:
        return {1}, {1}

    monkeypatch.setattr(
        availability_service, "_compute_available_days_for_doctor", _fake_compute_available_days_for_doctor
    )

    overview = availability_service.get_month_availability(year=2026, month=1, actor=None)

    assert len(overview.days) == 2

    d1 = overview.days[0]
    assert d1.day == 1
    assert d1.risk == RiskLevel.ok
    assert d1.risk_issues == []

    d2 = overview.days[1]
    assert d2.day == 2
    assert d2.risk == RiskLevel.critical
    assert d2.risk_issues == [NO_ONSITE_CANDIDATE, NO_ONCALL_CANDIDATE, NO_SPECIALIST]


def test_day_availability_drilldown_returns_only_ok_or_critical_and_core_issue_codes(monkeypatch):
    """
    Drilldown for day=2 in the same setup as the heatmap:
    no candidates => critical with the exact codes from the core classifier.
    """
    monkeypatch.setattr(availability_service, "days_in_month", lambda year, month: 2)
    monkeypatch.setattr(availability_service, "ensure_latest_checkpoints_for_period", lambda **kwargs: None)
    monkeypatch.setattr(availability_service, "get_period_status", lambda year, month: "future")

    doctors = [
        _FakeDoctor(id=1, role=DoctorRole.specialist, first_name="Spec", last_name="One"),
        _FakeDoctor(id=2, role=DoctorRole.resident, first_name="Res", last_name="Two"),
    ]
    monkeypatch.setattr(availability_service, "SessionLocal", _FakeSessionLocal(doctors))

    def _fake_compute_available_days_for_doctor(*args, **kwargs) -> Tuple[Set[int], Set[int]]:
        return {1}, {1}

    monkeypatch.setattr(
        availability_service, "_compute_available_days_for_doctor", _fake_compute_available_days_for_doctor
    )

    day_view = availability_service.get_day_availability(year=2026, month=1, day=2, actor=None)
    assert day_view is not None

    assert day_view.risk == RiskLevel.critical
    assert day_view.risk_issues == [NO_ONSITE_CANDIDATE, NO_ONCALL_CANDIDATE, NO_SPECIALIST]

    # Also ensure "only ok/critical" in practice (no alert allowed)
    assert day_view.risk in {RiskLevel.ok, RiskLevel.critical}
