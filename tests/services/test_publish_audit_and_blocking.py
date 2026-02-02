# tests/solver/test_publish_audit_and_blocking.py
"""
Publish flow tests.

Business policy:
1) publish(force=False) is blocked when diagnostics contain ANY critical findings.
   (Critical coverage findings must block publishing.)
2) publish(force=True) records an audit trail in payload.meta.exceptions:
   - kind="publish_acceptance"
   - code
   - justification
   - accepted_by_user_id
   - accepted_at (ISO string)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

import pytest
from sqlalchemy import select

from backend.models.common_enums import DoctorRole
from backend.models.orm.doctor import Doctor
from backend.models.orm.schedule import ScheduleVersion, ScheduleWorking
from backend.models.schemas.schedule import AcceptedException
from backend.services.errors import DomainError
from backend.services.scheduling_service import SchedulingService


def _seed_min_working_payload() -> Dict[str, Any]:
    """
    Minimal working payload that is valid for publish().

    We keep assignments empty on purpose:
    diagnostics should generate critical coverage findings -> publish must be blocked.
    """
    return {
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
            "exceptions": [],
            "solver_status": "OK",
        },
    }


def _insert_doctor_and_working(db, *, year: int, month: int) -> None:
    d = Doctor(
        id=1,
        first_name="Doc",
        last_name="One",
        role=DoctorRole.specialist,
        is_head=False,
        is_active=True,
    )
    db.add(d)

    w = ScheduleWorking(
        year=year,
        month=month,
        payload=_seed_min_working_payload(),
        lock_version=1,
        updated_by_user_id=None,
    )
    db.add(w)
    db.commit()


def test_publish_blocked_returns_context(db_session):
    year, month = 2026, 2
    _insert_doctor_and_working(db_session, year=year, month=month)

    svc = SchedulingService()

    with pytest.raises(DomainError) as ex:
        svc.publish(
            year,
            month,
            force=False,
            accepted_exceptions=[],
            note="Attempt publish without force",
            user_id=999,
        )

    assert str(ex.value) == "publish_blocked_by_hard_rules"
    assert isinstance(ex.value.context, dict)

    hard_violations = ex.value.context.get("hard_violations")
    assert isinstance(hard_violations, list)
    assert len(hard_violations) > 0

    # Critical coverage blockers must be present under this policy.
    codes = {str(v.get("code")) for v in hard_violations if isinstance(v, dict)}
    assert "coverage_missing_required_slot" in codes
    assert "coverage_no_specialist_day" in codes


def test_force_publish_records_accepted_exceptions_audit(db_session):
    year, month = 2026, 2
    _insert_doctor_and_working(db_session, year=year, month=month)

    svc = SchedulingService()

    resp = svc.publish(
        year,
        month,
        force=True,
        accepted_exceptions=[
            AcceptedException(
                code="coverage_missing_required_slot",
                justification="Emergency staffing shortage",
            )
        ],
        note="Force publish",
        user_id=777,
    )

    assert resp.published.version_id is not None
    published_id = int(resp.published.version_id)

    ver = db_session.execute(select(ScheduleVersion).where(ScheduleVersion.id == published_id)).scalar_one()
    payload = dict(ver.payload or {})
    meta = dict(payload.get("meta") or {})
    exceptions = list(meta.get("exceptions") or [])

    matches = [
        e
        for e in exceptions
        if isinstance(e, dict)
        and e.get("kind") == "publish_acceptance"
        and e.get("code") == "coverage_missing_required_slot"
    ]
    assert len(matches) == 1

    entry = matches[0]
    assert entry.get("justification") == "Emergency staffing shortage"
    assert entry.get("accepted_by_user_id") == 777

    accepted_at = entry.get("accepted_at")
    assert isinstance(accepted_at, str) and accepted_at
    datetime.fromisoformat(accepted_at.replace("Z", "+00:00"))
