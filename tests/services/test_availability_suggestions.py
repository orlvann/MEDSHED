"""
Unit tests for availability ignore suggestions.

We test only the pure suggestion logic:
- suggested_ignored_slots
- suggested_ignore_reason_codes

No DB involved, deterministic policy.
"""

from __future__ import annotations

import pytest

from backend.core.issues import NO_ONCALL_CANDIDATE, NO_ONSITE_CANDIDATE, NO_SPECIALIST
from backend.models.common_enums import ShiftType
from backend.services.availability_service import _suggest_ignored_slots_and_reasons

pytestmark = [pytest.mark.services]


def test_suggest_ignore_onsite_when_no_onsite_candidate():
    suggested, reasons = _suggest_ignored_slots_and_reasons(risk_issues=[NO_ONSITE_CANDIDATE])

    assert reasons == [NO_ONSITE_CANDIDATE]
    assert len(suggested) == 1
    assert suggested[0].shift_type == ShiftType.onsite


def test_suggest_ignore_oncall_when_no_oncall_candidate():
    suggested, reasons = _suggest_ignored_slots_and_reasons(risk_issues=[NO_ONCALL_CANDIDATE])

    assert reasons == [NO_ONCALL_CANDIDATE]
    assert len(suggested) == 1
    assert suggested[0].shift_type == ShiftType.oncall


def test_suggest_ignore_oncall_when_only_no_specialist():
    suggested, reasons = _suggest_ignored_slots_and_reasons(risk_issues=[NO_SPECIALIST])

    # Policy: if only NO_SPECIALIST blocks, ignore ONCALL (keep onsite more important)
    assert reasons == [NO_SPECIALIST]
    assert len(suggested) == 1
    assert suggested[0].shift_type == ShiftType.oncall


def test_do_not_add_extra_ignore_for_no_specialist_when_missing_slot_already_forces_ignore():
    suggested, reasons = _suggest_ignored_slots_and_reasons(risk_issues=[NO_ONSITE_CANDIDATE, NO_SPECIALIST])

    # Missing slot drives suggestion; NO_SPECIALIST becomes irrelevant once any slot is ignored.
    assert reasons == [NO_ONSITE_CANDIDATE]
    assert len(suggested) == 1
    assert suggested[0].shift_type == ShiftType.onsite
