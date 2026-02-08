# tests/solver/test_objective_fairness_rotation.py
"""
Soft-objective tests for fairness rotation (+1 carryover).

We verify that:
- When group target does not divide evenly, "rem" doctors get expected = base+1.
- The choice of WHO gets +1 is rotated month-to-month using carryover markers:
  had_plus1_<category>_last.

We also add defensive coverage:
- When carryover is missing (None), the solver should fall back to stable ordering (doctor_id).
- Weekend rotation is independent from weekday rotation (separate category).

Design:
- Tiny models (no DB / services).
- Non-consecutive days to avoid rest-rule influence.
- Oncall is fixed to a resident to keep the model stable and avoid extra tie-breakers.
"""

from __future__ import annotations

import pytest

from backend.core import engine
from backend.core.types import DoctorCarryover, MonthCarryover, SolverStatus
from backend.models.common_enums import DoctorRole, ShiftType
from tests.solver._helpers import assignments_to_map, solution_snapshot

pytestmark = [pytest.mark.solver]


def _onsite_assigned_docs(solution, *, days: list[int]) -> list[int]:
    """Return sorted list of doctor_ids assigned to onsite on given days."""
    m = assignments_to_map(solution)
    got = []
    for d in days:
        got.append(int(m[(int(d), ShiftType.onsite)]))
    return sorted(got)


@pytest.mark.unit
def test_fairness_rotation_prefers_doctors_without_plus1_last_month_for_onsite_weekdays(
    make_hard_model, make_doctors, make_preferences
):
    """
    Scenario:
    - 3 specialists in the same fairness group: docs 1,2,3
    - 1 resident: doc 4 (fixed oncall)
    - 2 NON-consecutive WEEKDAYS (so rest penalties do not influence anything)
    - onsite must be assigned on both days (2 onsite assignments total in this category)

    Group target for onsite weekdays in this tiny model is 2.
    With 3 specialists:
        base = 2 // 3 = 0
        rem  = 2 % 3  = 2
    So expected distribution should be:
        two doctors: expected=1
        one doctor:  expected=0

    Rotation rule:
    - doc 1 had +1 last month for onsite weekdays -> lower priority for +1 now
    - docs 2 and 3 did NOT -> they should receive the +1 this month

    Expected outcome:
    - onsite on the two days should be assigned to docs 2 and 3 (not doc 1),
      because that yields 0 deviation from expected values.
    """
    year = 2026
    month = 1

    # Two non-consecutive weekdays in Jan 2026:
    # Jan 6 = Tue, Jan 8 = Thu
    days = [6, 8]

    doctors = make_doctors(num_specialists=3, num_residents=1, include_head=False, start_id=1)
    prefs = make_preferences(doctors=doctors)

    specialist_ids = sorted([doc_id for doc_id, d in doctors.items() if d.role == DoctorRole.specialist])
    resident_id = [doc_id for doc_id, d in doctors.items() if d.role == DoctorRole.resident][0]

    assert specialist_ids == [1, 2, 3], "This test assumes specialists IDs are 1,2,3 for stable reasoning."

    carryover = MonthCarryover(
        prev_year=2025,
        prev_month=12,
        per_doctor={
            1: DoctorCarryover(had_plus1_onsite_weekday_last=True),
            2: DoctorCarryover(had_plus1_onsite_weekday_last=False),
            3: DoctorCarryover(had_plus1_onsite_weekday_last=False),
            resident_id: DoctorCarryover(),
        },
    )

    allowed_slots = {
        (6, ShiftType.onsite): list(specialist_ids),
        (6, ShiftType.oncall): [resident_id],
        (8, ShiftType.onsite): list(specialist_ids),
        (8, ShiftType.oncall): [resident_id],
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

    # IMPORTANT:
    # The fixture make_hard_model does not accept carryover=... as a kwarg.
    # We attach it directly to the HardModel instance.
    model.carryover = carryover

    sol = engine.build_and_solve(model)
    assert sol.status == SolverStatus.OK, solution_snapshot(model, sol)

    got = _onsite_assigned_docs(sol, days=days)
    assert got == [2, 3], (
        "Expected weekday +1 rotation to prioritize doctors WITHOUT plus1 last month.\n"
        f"got={got} expected=[2,3]\n"
        f"{solution_snapshot(model, sol)}"
    )


@pytest.mark.unit
def test_fairness_rotation_without_carryover_falls_back_to_stable_doctor_id_order_for_weekdays(
    make_hard_model, make_doctors, make_preferences
):
    """
    Defensive test:
    - Same model as the weekday rotation test,
      BUT carryover is None (missing).

    Business expectation:
    - We still must assign 2 weekday onsite shifts among 3 specialists.
    - base/rem logic still ensures two doctors have expected=1 and one doctor expected=0.
    - Without carryover, the selection of who gets +1 should be stable/deterministic:
      sorted by doctor_id -> docs 1 and 2 get expected=1, doc 3 gets expected=0.

    Expected outcome:
    - onsite assignments should go to docs 1 and 2 (not doc 3),
      because that yields 0 deviation from expected values.
    """
    year = 2026
    month = 1
    days = [6, 8]  # Tue + Thu (non-consecutive weekdays)

    doctors = make_doctors(num_specialists=3, num_residents=1, include_head=False, start_id=1)
    prefs = make_preferences(doctors=doctors)

    specialist_ids = sorted([doc_id for doc_id, d in doctors.items() if d.role == DoctorRole.specialist])
    resident_id = [doc_id for doc_id, d in doctors.items() if d.role == DoctorRole.resident][0]

    assert specialist_ids == [1, 2, 3], "This test assumes specialists IDs are 1,2,3 for stable reasoning."

    allowed_slots = {
        (6, ShiftType.onsite): list(specialist_ids),
        (6, ShiftType.oncall): [resident_id],
        (8, ShiftType.onsite): list(specialist_ids),
        (8, ShiftType.oncall): [resident_id],
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

    # Explicitly set missing carryover (None).
    model.carryover = None

    sol = engine.build_and_solve(model)
    assert sol.status == SolverStatus.OK, solution_snapshot(model, sol)

    got = _onsite_assigned_docs(sol, days=days)
    assert got == [1, 2], (
        "Expected fallback ordering (doctor_id) when carryover is missing.\n"
        f"got={got} expected=[1,2]\n"
        f"{solution_snapshot(model, sol)}"
    )


@pytest.mark.unit
def test_fairness_rotation_prefers_doctors_without_plus1_last_month_for_onsite_weekends(
    make_hard_model, make_doctors, make_preferences
):
    """
    Weekend category rotation test (separate bucket from weekdays).

    Scenario:
    - 3 specialists: docs 1,2,3
    - 1 resident fixed oncall
    - 2 NON-consecutive WEEKEND days in Jan 2026:
        Jan 3, 2026  = Saturday
        Jan 10, 2026 = Saturday
      (non-consecutive -> no rest-rule influence)

    We assign onsite on both days -> 2 weekend onsite assignments.

    base/rem same as before:
      base = 2 // 3 = 0
      rem  = 2 % 3  = 2
    So two specialists should have expected=1 weekend onsite, one should have expected=0.

    Rotation rule (weekend bucket):
    - doc 1 had +1 last month for onsite WEEKENDS -> lower priority now
    - docs 2 and 3 should receive +1 now

    Expected outcome:
    - onsite on the two weekend days should go to docs 2 and 3 (not doc 1).
    """
    year = 2026
    month = 1

    # Two non-consecutive weekend days in Jan 2026 (both Saturdays).
    days = [3, 10]

    doctors = make_doctors(num_specialists=3, num_residents=1, include_head=False, start_id=1)
    prefs = make_preferences(doctors=doctors)

    specialist_ids = sorted([doc_id for doc_id, d in doctors.items() if d.role == DoctorRole.specialist])
    resident_id = [doc_id for doc_id, d in doctors.items() if d.role == DoctorRole.resident][0]

    assert specialist_ids == [1, 2, 3], "This test assumes specialists IDs are 1,2,3 for stable reasoning."

    carryover = MonthCarryover(
        prev_year=2025,
        prev_month=12,
        per_doctor={
            1: DoctorCarryover(had_plus1_onsite_weekend_last=True),
            2: DoctorCarryover(had_plus1_onsite_weekend_last=False),
            3: DoctorCarryover(had_plus1_onsite_weekend_last=False),
            resident_id: DoctorCarryover(),
        },
    )

    allowed_slots = {
        (3, ShiftType.onsite): list(specialist_ids),
        (3, ShiftType.oncall): [resident_id],
        (10, ShiftType.onsite): list(specialist_ids),
        (10, ShiftType.oncall): [resident_id],
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

    model.carryover = carryover

    sol = engine.build_and_solve(model)
    assert sol.status == SolverStatus.OK, solution_snapshot(model, sol)

    got = _onsite_assigned_docs(sol, days=days)
    assert got == [2, 3], (
        "Expected weekend +1 rotation to prioritize doctors WITHOUT plus1 last month.\n"
        f"got={got} expected=[2,3]\n"
        f"{solution_snapshot(model, sol)}"
    )
