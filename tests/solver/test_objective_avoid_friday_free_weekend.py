from __future__ import annotations

from backend.core.engine import build_and_solve
from backend.models.common_enums import ShiftType
from tests.solver._helpers import assignments_to_map, solution_snapshot


def test_avoid_friday_if_weekend_off_prefers_doctor_who_works_weekend(make_hard_model, make_doctors, make_preferences):
    """
    INTEGRATION TEST.

    We create a Friday + weekend scenario (Jan 2026: day 2=Fri, day 3=Sat, day 4=Sun).

    Friday onsite has two candidates (A or B).
    B is forced to work the weekend. A is forced to have the whole weekend off.

    The objective adds a small penalty when someone works on Friday AND has a fully free weekend after it.
    So the solver should prefer assigning Friday onsite to B (because B does not have a free weekend).
    """
    doctors = make_doctors(num_specialists=2, num_residents=2, include_head=False, start_id=1)
    prefs = make_preferences(doctors=doctors)

    # IDs from make_doctors(start_id=1): specialists=1,2 ; residents=3,4
    a = 1
    b = 2
    c = 3
    d = 4

    # IMPORTANT:
    # We pass days in a non-consecutive order so rest rules do not influence this test.
    # The Friday/weekend rule is based on day numbers (fri+1, fri+2), not on list order.
    days = [2, 4, 3]

    allowed_slots = {
        # Day 2 (Fri): onsite has a choice, oncall is fixed.
        (2, ShiftType.onsite): [a, b],
        (2, ShiftType.oncall): [c],
        # Day 3 (Sat): B works weekend (fixed).
        (3, ShiftType.onsite): [b],
        (3, ShiftType.oncall): [c],
        # Day 4 (Sun): B works weekend (fixed), oncall is D.
        (4, ShiftType.onsite): [b],
        (4, ShiftType.oncall): [d],
    }

    model = make_hard_model(
        year=2026,
        month=1,
        days=days,
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_days=set(),
        ignore_slots=set(),
        allowed_slots=allowed_slots,
    )

    solution = build_and_solve(model)
    slot_map = assignments_to_map(solution)

    assert solution.status.value == "OK", solution_snapshot(model, solution)
    assert slot_map[(2, ShiftType.onsite)] == b, solution_snapshot(model, solution)


def test_avoid_friday_if_weekend_off_is_soft_not_blocking(make_hard_model, make_doctors, make_preferences):
    """
    INTEGRATION TEST.

    Same Fri+weekend setup, but Friday onsite has ONLY one candidate (A).
    Even if A has the whole weekend off (so the penalty triggers),
    the solver must still return a feasible schedule (soft objectives must not block).
    """
    doctors = make_doctors(num_specialists=2, num_residents=2, include_head=False, start_id=1)
    prefs = make_preferences(doctors=doctors)

    a = 1
    b = 2
    c = 3
    d = 4

    days = [2, 4, 3]

    allowed_slots = {
        (2, ShiftType.onsite): [a],  # no choice here
        (2, ShiftType.oncall): [c],
        (3, ShiftType.onsite): [b],
        (3, ShiftType.oncall): [c],
        (4, ShiftType.onsite): [b],
        (4, ShiftType.oncall): [d],
    }

    model = make_hard_model(
        year=2026,
        month=1,
        days=days,
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_days=set(),
        ignore_slots=set(),
        allowed_slots=allowed_slots,
    )

    solution = build_and_solve(model)
    slot_map = assignments_to_map(solution)

    assert solution.status.value == "OK", solution_snapshot(model, solution)
    assert slot_map[(2, ShiftType.onsite)] == a, solution_snapshot(model, solution)


def test_friday_rule_is_skipped_if_weekend_days_are_missing(make_hard_model, make_doctors, make_preferences):
    """
    DEFENSIVE TEST.

    We include only a single Friday day in the model (no Sat/Sun).
    The objective must simply skip this rule (no crash, no special requirements).
    """
    doctors = make_doctors(num_specialists=1, num_residents=1, include_head=False, start_id=1)
    prefs = make_preferences(doctors=doctors)

    allowed_slots = {
        (2, ShiftType.onsite): [1],
        (2, ShiftType.oncall): [2],
    }

    model = make_hard_model(
        year=2026,
        month=1,
        days=[2],
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_days=set(),
        ignore_slots=set(),
        allowed_slots=allowed_slots,
    )

    solution = build_and_solve(model)

    assert solution.status.value == "OK", solution_snapshot(model, solution)
