from __future__ import annotations

from backend.core import diagnostics as core_diagnostics
from backend.core.types import DoctorInput, PreferencesInput, ProblemData
from backend.models.common_enums import DoctorRole


def test_ignore_exceptions_do_not_change_preference_fulfillment_pct():
    """
    Policy: ignore-slot markers are audit/UI hints only.
    They MUST NOT change preference_fulfillment_pct.
    """
    problem = ProblemData(
        year=2026,
        month=2,
        days=[1],
        weekdays={1: 0},
        doctors={
            101: DoctorInput(id=101, role=DoctorRole.specialist, is_head=False, is_active=True),
        },
        preferences={
            101: PreferencesInput(
                doctor_id=101,
                unavailable_onsite_days=[],
                unavailable_oncall_days=[],
                preferred_onsite_days=[1],
                preferred_oncall_days=[],
            )
        },
        participant_doctor_ids={101},
        ignore_slots=set(),
    )

    payload_base = {
        "participant_doctor_ids": [101],
        "assignments": [],  # no assignments
        "meta": {"labels": [], "exceptions": []},
    }

    payload_with_ignore = {
        **payload_base,
        "meta": {
            "labels": [],
            "exceptions": [
                # Slot marker (ignored gap) - should not affect preference KPI
                {"kind": "generation_ignore", "code": "coverage_ignored_slot", "day": 1, "shift_type": "onsite"},
            ],
        },
    }

    q1 = core_diagnostics.compute_quality(problem=problem, payload=payload_base)
    q2 = core_diagnostics.compute_quality(problem=problem, payload=payload_with_ignore)

    p1 = (q1.get("summary") or {}).get("preference_fulfillment_pct")
    p2 = (q2.get("summary") or {}).get("preference_fulfillment_pct")

    assert p1 == p2
