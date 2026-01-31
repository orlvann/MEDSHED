# tests/solver/test_publish_audit_and_blocking.py
"""
Publish flow tests.

What we verify:
1) publish(force=False) is blocked when hard violations exist AND returns context payload
   (DomainError.context contains hard_violations).
2) publish(force=True) records an audit trail in payload.meta.exceptions:
   - accepted exception code
   - justification
   - accepted_by_user_id
   - accepted_at (ISO string)

Notes:
- We monkeypatch _hard_rule_violations() because MVP may return [] in prod code.
- We keep the payload minimal: empty assignments are fine for these tests.

Important (separation of concerns):
- Storage stays backward compatible: publish writes audit entries into payload.meta.exceptions.
- Diagnostics response will later PROJECT those audit entries into details.audit[],
  but this test verifies persistence only (DB payload).
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
    Build a minimal working payload that is valid for publish().
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
            # This field is optional, but we include it explicitly.
            "exceptions": [],
            "solver_status": "OK",
        },
    }


def _insert_doctor_and_working(db, *, year: int, month: int) -> None:
    """
    Insert a minimal Doctor and a ScheduleWorking row.
    """
    # 1) Doctor row (must exist, because some flows read doctors)
    d = Doctor(
        id=1,
        first_name="Doc",
        last_name="One",
        role=DoctorRole.specialist,
        is_head=False,
        is_active=True,
    )
    db.add(d)

    # 2) Working row with minimal payload
    w = ScheduleWorking(
        year=year,
        month=month,
        payload=_seed_min_working_payload(),
        lock_version=1,
        updated_by_user_id=None,
    )
    db.add(w)
    db.commit()


def test_publish_blocked_returns_context(monkeypatch, db_session):
    """
    publish(force=False) should be blocked by hard violations and return DomainError with context.

    Expected behavior:
    - raises DomainError("publish_blocked_by_hard_rules")
    - e.context contains {"hard_violations": [...]} for FE
    """
    year, month = 2026, 2
    _insert_doctor_and_working(db_session, year=year, month=month)

    # Pretend that hard rule validator found violations.
    hard_violations = [
        {"code": "hard_missing_coverage", "message": "Coverage is missing for day 3 onsite."},
        {"code": "hard_double_shift", "message": "Doctor 1 has two shifts on day 5."},
    ]

    # Monkeypatch the function used inside SchedulingService.publish()
    from backend.services import scheduling_service as svc_mod

    monkeypatch.setattr(svc_mod, "_hard_rule_violations", lambda payload: hard_violations)

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

    # Machine code must stay stable.
    assert str(ex.value) == "publish_blocked_by_hard_rules"

    # Context must exist and contain hard violations for FE.
    assert isinstance(ex.value.context, dict)
    assert ex.value.context.get("hard_violations") == hard_violations


def test_force_publish_records_accepted_exceptions_audit(monkeypatch, db_session):
    """
    publish(force=True) should record accepted_exceptions audit trail inside payload.meta.exceptions.
    """
    year, month = 2026, 2
    _insert_doctor_and_working(db_session, year=year, month=month)

    # Violations that can be force-accepted.
    hard_violations = [{"code": "hard_missing_coverage", "message": "Coverage missing."}]

    from backend.services import scheduling_service as svc_mod

    monkeypatch.setattr(svc_mod, "_hard_rule_violations", lambda payload: hard_violations)

    svc = SchedulingService()

    resp = svc.publish(
        year,
        month,
        force=True,
        accepted_exceptions=[
            AcceptedException(code="hard_missing_coverage", justification="Emergency staffing shortage")
        ],
        note="Force publish",
        user_id=777,
    )

    # Response should contain a published version_id
    assert resp.published.version_id is not None
    published_id = int(resp.published.version_id)

    # Verify DB payload was stored with audit info in meta.exceptions (storage stays compatible)
    ver = db_session.execute(select(ScheduleVersion).where(ScheduleVersion.id == published_id)).scalar_one()
    payload = dict(ver.payload or {})
    meta = dict(payload.get("meta") or {})
    exceptions = list(meta.get("exceptions") or [])

    # Find our accepted exception entry
    matches = [e for e in exceptions if isinstance(e, dict) and e.get("code") == "hard_missing_coverage"]
    assert len(matches) == 1

    entry = matches[0]
    assert entry.get("justification") == "Emergency staffing shortage"
    assert entry.get("accepted_by_user_id") == 777

    # accepted_at should be an ISO datetime string
    accepted_at = entry.get("accepted_at")
    assert isinstance(accepted_at, str) and accepted_at

    # This will raise ValueError if format is invalid -> good.
    datetime.fromisoformat(accepted_at.replace("Z", "+00:00"))
