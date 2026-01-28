# test_objective_weekday_patterns.py
"""
Soft-objective tests for weekday patterns.

We verify that weekday-pattern terms break ties between multiple FEASIBLE solutions:

* preferred_*_weekdays -> small bonus (solver prefers it)
* avoid_*_weekdays -> small penalty (solver avoids it)

Scope:

* tiny model (no DB),
* 1 day only (rest rules do not matter),
* totals / fairness should not differentiate solutions (tie),
  so weekday patterns decide.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from backend.core import engine
from backend.models.common_enums import DoctorRole, ShiftType

from ._helpers import assignments_to_map, solution_snapshot

pytestmark = [pytest.mark.solver]


def test_preferred_weekday_breaks_tie(make_hard_model, make_doctors, make_preferences):
    """
    INTEGRATION TEST.

    ```
    Scenario:
    - 1 day where weekday == X
    - 2 specialists compete for onsite
    - oncall is fixed to a resident
    - only one specialist has preferred_onsite_weekdays=[X]

    Expectation:
    - solver chooses the preferred specialist for onsite.
    """
    year = 2026
    month = 1
    day = 1
    days = [day]

    weekday_x = datetime(year, month, day).weekday()

    doctors = make_doctors(num_specialists=2, num_residents=1, include_head=False, start_id=1)
    specialist_ids = [doc_id for doc_id, d in doctors.items() if d.role == DoctorRole.specialist]
    resident_ids = [doc_id for doc_id, d in doctors.items() if d.role == DoctorRole.resident]

    assert len(specialist_ids) == 2, "Test setup requires exactly 2 specialists."
    assert len(resident_ids) == 1, "Test setup requires exactly 1 resident."

    resident_id = resident_ids[0]
    preferred_doc_id = specialist_ids[0]
    other_doc_id = specialist_ids[1]

    prefs = make_preferences(doctors=doctors)

    # Only one specialist prefers this weekday for onsite.
    prefs[preferred_doc_id].preferred_onsite_weekdays = [weekday_x]
    prefs[other_doc_id].preferred_onsite_weekdays = []

    allowed_slots = {
        (day, ShiftType.onsite): list(specialist_ids),
        (day, ShiftType.oncall): [resident_id],
    }

    model = make_hard_model(
        year=year,
        month=month,
        days=days,
        active_days=days,
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_slots=set(),
        allowed_slots=allowed_slots,
    )

    solution = engine.build_and_solve(model)
    assert (
        solution.status.value == "OK"
    ), f"Expected OK (feasible schedule), got {solution.status}.\n{solution_snapshot(model, solution)}"

    m = assignments_to_map(solution)
    assert m[(day, ShiftType.onsite)] == preferred_doc_id, (
        "Solver should pick the specialist with preferred weekday for onsite.\n"
        f"weekday_x={weekday_x}\n"
        f"onsite_got={m[(day, ShiftType.onsite)]} preferred_doc_id={preferred_doc_id}\n"
        f"{solution_snapshot(model, solution)}"
    )


def test_avoid_weekday_breaks_tie(make_hard_model, make_doctors, make_preferences):
    """
    INTEGRATION TEST.

    ```
    Scenario:
    - 1 day where weekday == X
    - 2 specialists compete for onsite
    - oncall is fixed to a resident
    - one specialist has avoid_onsite_weekdays=[X]

    Expectation:
    - solver does NOT choose the avoiding specialist for onsite.
    """
    year = 2026
    month = 1
    day = 1
    days = [day]

    weekday_x = datetime(year, month, day).weekday()

    doctors = make_doctors(num_specialists=2, num_residents=1, include_head=False, start_id=1)
    specialist_ids = [doc_id for doc_id, d in doctors.items() if d.role == DoctorRole.specialist]
    resident_ids = [doc_id for doc_id, d in doctors.items() if d.role == DoctorRole.resident]

    assert len(specialist_ids) == 2, "Test setup requires exactly 2 specialists."
    assert len(resident_ids) == 1, "Test setup requires exactly 1 resident."

    resident_id = resident_ids[0]
    avoid_doc_id = specialist_ids[0]
    other_doc_id = specialist_ids[1]

    prefs = make_preferences(doctors=doctors)

    # One specialist wants to avoid this weekday for onsite.
    prefs[avoid_doc_id].avoid_onsite_weekdays = [weekday_x]
    prefs[other_doc_id].avoid_onsite_weekdays = []

    allowed_slots = {
        (day, ShiftType.onsite): list(specialist_ids),
        (day, ShiftType.oncall): [resident_id],
    }

    model = make_hard_model(
        year=year,
        month=month,
        days=days,
        active_days=days,
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_slots=set(),
        allowed_slots=allowed_slots,
    )

    solution = engine.build_and_solve(model)
    assert (
        solution.status.value == "OK"
    ), f"Expected OK (feasible schedule), got {solution.status}.\n{solution_snapshot(model, solution)}"

    m = assignments_to_map(solution)
    assert m[(day, ShiftType.onsite)] == other_doc_id, (
        "Solver should avoid assigning onsite to the specialist who avoids this weekday.\n"
        f"weekday_x={weekday_x}\n"
        f"onsite_got={m[(day, ShiftType.onsite)]} avoid_doc_id={avoid_doc_id} other_doc_id={other_doc_id}\n"
        f"{solution_snapshot(model, solution)}"
    )
