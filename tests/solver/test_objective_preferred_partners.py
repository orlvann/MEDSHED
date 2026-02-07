"""
Soft-objective tests for preferred partners.

Goal:
- Add a small bonus when two preferred partners work on the same day (any shift).
- This should work only as a tie-breaker (must not affect feasibility).

We use non-consecutive days to avoid rest-rule influence.
We keep other preferences empty so only the partner bonus can differentiate solutions.
"""

from __future__ import annotations

import pytest

from backend.core import engine
from backend.core.types import SolverStatus
from backend.models.common_enums import DoctorRole, ShiftType

pytestmark = [pytest.mark.solver]


def _works_day(solution, *, doc_id: int, day: int) -> bool:
    """Return True if doc has ANY assignment on this day (onsite or oncall)."""
    for a in solution.assignments:
        if int(a.day) == int(day) and int(a.doctor_id) == int(doc_id):
            return True
    return False


def _together_count(solution, *, a_id: int, b_id: int, days: list[int]) -> int:
    """Count how many days both doctors work on the same day."""
    cnt = 0
    for d in days:
        if _works_day(solution, doc_id=a_id, day=d) and _works_day(solution, doc_id=b_id, day=d):
            cnt += 1
    return cnt


def test_partner_bonus_pushes_partners_to_work_same_days(make_hard_model, make_doctors, make_preferences):
    """
    INTEGRATION TEST.

    Setup:
    - days: [6, 8] (non-consecutive)
    - 2 specialists: A, B
    - 1 resident: E
    - onsite can be done ONLY by specialists
    - oncall can be done by anyone (including specialists)

    Why this setup?
    - If we allow resident to do everything, fairness/totals may prefer "one specialist per day"
      and push oncall into the resident, which makes partners never work together.
    - Here we keep the model flexible (oncall can be specialist or resident),
      but we avoid the situation where non-partner objectives dominate the choice.

    Expectation:
    - With partner bonus A prefers B, the solver should pick a schedule that maximizes
      together days for (A,B). In this 2-day setup the best is: together on BOTH days.
    """
    year = 2026
    month = 1
    days = [6, 8]

    doctors = make_doctors(num_specialists=2, num_residents=1, include_head=False, start_id=1)
    specialist_ids = [doc_id for doc_id, d in doctors.items() if d.role == DoctorRole.specialist]
    resident_ids = [doc_id for doc_id, d in doctors.items() if d.role == DoctorRole.resident]

    assert len(specialist_ids) == 2, "Test setup requires exactly 2 specialists."
    assert len(resident_ids) == 1, "Test setup requires exactly 1 resident."

    a_id = specialist_ids[0]
    b_id = specialist_ids[1]
    r_id = resident_ids[0]

    prefs = make_preferences(doctors=doctors)

    # Partner preference: A prefers to work with B.
    prefs[a_id].preferred_partners = [b_id]

    # IMPORTANT STABILITY NOTE:
    # Neutralize totals/fairness pressure that could otherwise push oncall into the resident.
    # We want the model to naturally allow A+B to be "together" without being dominated
    # by other objectives.
    prefs[a_id].target_onsite_total = 1
    prefs[b_id].target_onsite_total = 1
    prefs[a_id].target_oncall_total = 1
    prefs[b_id].target_oncall_total = 1

    # Resident is not "expected" to take oncall in this tiny scenario.
    prefs[r_id].target_oncall_total = 0

    allowed_slots = {}
    for d in days:
        # onsite: only specialists
        allowed_slots[(d, ShiftType.onsite)] = list(specialist_ids)
        # oncall: anyone
        allowed_slots[(d, ShiftType.oncall)] = list(doctors.keys())

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

    sol = engine.build_and_solve(model)
    assert sol.status == SolverStatus.OK, f"Expected OK, got {sol.status}"

    # With the bonus, best outcome is: A and B work together on BOTH days.
    got = _together_count(sol, a_id=a_id, b_id=b_id, days=days)
    assert got == len(days), f"Expected partners together on all days. got={got} days={days}"


def test_partner_bonus_increases_or_keeps_together_count(make_hard_model, make_doctors, make_preferences):
    """
    INTEGRATION TEST.

    We run the SAME model twice, changing only ONE thing: partner preference.

    Run A (with bonus):
    - doctor A has preferred_partners=[B] -> solver gets a small bonus when A and B work on the same day.

    Run B (no bonus):
    - doctor A has preferred_partners=[] -> no reason to prefer "together" days.

    We count together_count(A,B):
    - how many days both A and B work on that day (any shift: onsite or oncall).

    Expected behavior:
    - Adding the partner bonus should not make the solution WORSE for "together" days.
      So: together_count(with_bonus) >= together_count(without_bonus).

    Why we do NOT assert "without_bonus == 0":
    - even without the bonus, the solver may pick a "together" schedule by chance (ties / multiple optimal solutions),
      so a strict "not together" assertion would be flaky.
    """
    year = 2026
    month = 1
    days = [6, 8]

    doctors = make_doctors(num_specialists=2, num_residents=1, include_head=False, start_id=1)
    specialist_ids = [doc_id for doc_id, d in doctors.items() if d.role == DoctorRole.specialist]
    resident_ids = [doc_id for doc_id, d in doctors.items() if d.role == DoctorRole.resident]

    a_id = specialist_ids[0]
    b_id = specialist_ids[1]
    r_id = resident_ids[0]

    allowed_slots = {}
    for d in days:
        allowed_slots[(d, ShiftType.onsite)] = list(specialist_ids)
        allowed_slots[(d, ShiftType.oncall)] = list(doctors.keys())

    # Run A: with partner
    prefs_with = make_preferences(doctors=doctors)
    prefs_with[a_id].preferred_partners = [b_id]

    # Keep the same stabilization targets as in the test above.
    prefs_with[a_id].target_onsite_total = 1
    prefs_with[b_id].target_onsite_total = 1
    prefs_with[a_id].target_oncall_total = 1
    prefs_with[b_id].target_oncall_total = 1
    prefs_with[r_id].target_oncall_total = 0

    model_with = make_hard_model(
        year=year,
        month=month,
        days=days,
        active_days=days,
        doctors=doctors,
        preferences=prefs_with,
        participant_doctor_ids=set(doctors.keys()),
        ignore_slots=set(),
        allowed_slots=allowed_slots,
    )
    sol_with = engine.build_and_solve(model_with)
    assert sol_with.status == SolverStatus.OK, f"Expected OK (with partner), got {sol_with.status}"

    # Run B: without partner
    prefs_without = make_preferences(doctors=doctors)

    prefs_without[a_id].target_onsite_total = 1
    prefs_without[b_id].target_onsite_total = 1
    prefs_without[a_id].target_oncall_total = 1
    prefs_without[b_id].target_oncall_total = 1
    prefs_without[r_id].target_oncall_total = 0

    model_without = make_hard_model(
        year=year,
        month=month,
        days=days,
        active_days=days,
        doctors=doctors,
        preferences=prefs_without,
        participant_doctor_ids=set(doctors.keys()),
        ignore_slots=set(),
        allowed_slots=allowed_slots,
    )
    sol_without = engine.build_and_solve(model_without)
    assert sol_without.status == SolverStatus.OK, f"Expected OK (without partner), got {sol_without.status}"

    got_with = _together_count(sol_with, a_id=a_id, b_id=b_id, days=days)
    got_without = _together_count(sol_without, a_id=a_id, b_id=b_id, days=days)

    assert got_with >= got_without, f"Expected with_partner >= without_partner. with={got_with} without={got_without}"
