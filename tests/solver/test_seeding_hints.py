# tests/solver/test_seeding_hints.py
"""
Tests for seeding.generate_initial_hints().

IMPORTANT:
- These tests do NOT go through engine.build_and_solve().
- They only verify what seeding *suggests* (hint map), not feasibility validation.

We reuse fixtures from tests/solver/conftest.py:
- make_hard_model
- make_preferences
- make_problem_data
"""

from __future__ import annotations

import pytest

from backend.core import seeding
from backend.core.types import DoctorInput, PreferencesInput
from backend.models.common_enums import DoctorRole, ShiftType

pytestmark = [pytest.mark.solver]


def _slots_from_hints(hints: dict[tuple[int, int, ShiftType], int]) -> set[tuple[int, ShiftType]]:
    """
    Convert hint keys into a set of slots (day, shift_type).

    Each hint key is (day, doctor_id, shift_type).

    We count only hints with value==1 (we ignore any future extensions).
    """
    out: set[tuple[int, ShiftType]] = set()
    for (day, _doc_id, shift_type), val in hints.items():
        if int(val) == 1:
            out.add((int(day), shift_type))
    return out


def _hinted_doctors_for_slot(
    *, hints: dict[tuple[int, int, ShiftType], int], day: int, shift_type: ShiftType
) -> list[int]:
    """
    Return sorted doctor_ids hinted for a concrete slot (day, shift_type).

    We count only hints with value==1.
    """
    out: list[int] = []
    for (d, doc_id, st), val in hints.items():
        if int(val) != 1:
            continue
        if int(d) == int(day) and st == shift_type:
            out.append(int(doc_id))
    return sorted(out)


def test_seeding_includes_head_commitment_hint(make_hard_model, make_preferences, make_problem_data):
    """
    Head commitment should be suggested as a hint:
    - (day, head_id, shift_type) -> 1

    And for that slot, there should be exactly ONE hinted doctor (the head).
    """
    doctors: dict[int, DoctorInput] = {
        10: DoctorInput(id=10, role=DoctorRole.specialist, is_head=True),
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=False),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
    }

    # Build preferences with a head commitment: day=1 onsite.
    preferences = make_preferences(doctors=doctors)
    preferences[10].preferred_onsite_days = [1]

    model = make_hard_model(
        year=2026,
        month=1,
        days=[1],
        active_days=[1],
        doctors=doctors,
        preferences=preferences,
        participant_doctor_ids=set(doctors.keys()),
        ignore_days=set(),
        ignore_slots=set(),
        allowed_slots={
            (1, ShiftType.onsite): [1, 2, 10],
            (1, ShiftType.oncall): [1, 2, 10],
        },
    )

    problem_view = make_problem_data(
        year=model.year,
        month=model.month,
        days=list(model.days),
        doctors=dict(model.doctors),
        preferences=dict(model.preferences),
        participant_doctor_ids=set(model.participant_doctor_ids),
        ignore_days=set(model.ignore_days),
        ignore_slots=set(model.ignore_slots),
    )

    hints = seeding.generate_initial_hints(model=model, problem=problem_view)

    # Must contain the exact head hint.
    assert hints.get((1, 10, ShiftType.onsite)) == 1, "Expected head commitment hint (day=1, onsite, head_id=10)."

    # For the same slot (1, onsite), there must be exactly one hinted doctor and it must be the head.
    hinted_doctors_for_slot = _hinted_doctors_for_slot(hints=hints, day=1, shift_type=ShiftType.onsite)
    assert hinted_doctors_for_slot == [
        10
    ], f"Expected only head hinted for slot (day=1, onsite). Got {hinted_doctors_for_slot}"


def test_top_k_excludes_slots_already_seeded_by_head_commitments(make_hard_model, make_preferences, make_problem_data):
    """
    This test checks the interaction between:
    - STEP 1: seeding head commitments
    - STEP 2: seeding TOP K hardest slots by difficulty

    Confirmed behavior:
    - candidate_slots for TOP K excludes slots already seeded by head commitments.

    We set up:
    - 6 days => 12 slots total
    - 1 head commitment on (day=1, onsite)
    - no ignores
    Expect:
    - commitment slot (1, onsite) has exactly one hinted doctor: the head
    - TOP K seeds 10 additional slots (K=min(10, remaining_slots=11) => 10)
    - total seeded slots = 1 (commitment) + 10 (TOP K) = 11
    """
    year = 2026
    month = 1
    days = [1, 2, 3, 4, 5, 6]

    # Doctors:
    # - head=10 is a specialist
    # - others are specialists (so the "prefer specialist if day has none yet" bonus does not change picks)
    doctors: dict[int, DoctorInput] = {
        10: DoctorInput(id=10, role=DoctorRole.specialist, is_head=True),
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=False),
        2: DoctorInput(id=2, role=DoctorRole.specialist, is_head=False),
        3: DoctorInput(id=3, role=DoctorRole.specialist, is_head=False),
        4: DoctorInput(id=4, role=DoctorRole.specialist, is_head=False),
        5: DoctorInput(id=5, role=DoctorRole.specialist, is_head=False),
    }

    preferences: dict[int, PreferencesInput] = make_preferences(doctors=doctors)
    preferences[10].preferred_onsite_days = [1]  # head commitment on day 1 onsite

    # Make difficulty strictly increasing (len 1..12) with unique smallest doctor_id per slot,
    # but ALSO ensure the head is allowed on its commitment slot.
    #
    # We do NOT want the "same doctor onsite+oncall same day" rule to block TOP K,
    # so we ensure day=1 oncall smallest candidate is NOT the head.
    allowed_slots: dict[tuple[int, ShiftType], list[int]] = {}

    # We use extra synthetic candidate ids too, but we do not need to register them in doctors
    # because seeding only reads allowed_slots and preferences for the chosen doc_id.
    # Still, for safety, we keep chosen smallest candidates among existing doctors (1..5 and head=10).
    slot_order: list[tuple[int, ShiftType]] = []
    for day in days:
        for st in (ShiftType.onsite, ShiftType.oncall):
            slot_order.append((day, st))

    # Assign per-slot "smallest deterministic pick" using existing doctor ids, rotating.
    # Ensure (1, onsite) uses head=10 to match commitment.
    smallest_by_slot: dict[tuple[int, ShiftType], int] = {}
    smallest_by_slot[(1, ShiftType.onsite)] = 10
    rotation = [1, 2, 3, 4, 5]  # avoid head for other slots
    rot_idx = 0
    for day, st in slot_order:
        if (day, st) == (1, ShiftType.onsite):
            continue
        smallest_by_slot[(day, st)] = rotation[rot_idx % len(rotation)]
        rot_idx += 1

    difficulty = 1
    for day, st in slot_order:
        base_id = smallest_by_slot[(day, st)]
        extra_ids = list(range(1000 + difficulty * 10, 1000 + difficulty * 10 + (difficulty - 1)))
        allowed_slots[(day, st)] = [base_id] + extra_ids
        difficulty += 1

    model = make_hard_model(
        year=year,
        month=month,
        days=list(days),
        active_days=list(days),
        doctors=doctors,
        preferences=preferences,
        participant_doctor_ids=set(doctors.keys()),
        ignore_days=set(),
        ignore_slots=set(),
        allowed_slots=allowed_slots,
    )

    problem_view = make_problem_data(
        year=year,
        month=month,
        days=list(days),
        doctors=doctors,
        preferences=preferences,
        participant_doctor_ids=set(doctors.keys()),
        ignore_days=set(),
        ignore_slots=set(),
    )

    hints = seeding.generate_initial_hints(model=model, problem=problem_view)

    # Commitment slot must have only the head hinted.
    hinted_commitment = _hinted_doctors_for_slot(hints=hints, day=1, shift_type=ShiftType.onsite)
    assert hinted_commitment == [10], f"Expected only head hinted for commitment slot. Got {hinted_commitment}"

    seeded_slots = _slots_from_hints(hints)

    # Total seeded slots = 1 commitment + 10 TOP K = 11.
    # (TOP K is computed after removing already-seeded slots.)
    assert len(seeded_slots) == 11, (
        f"Expected 11 seeded slots total (1 commitment + 10 TOP K), got {len(seeded_slots)}.\n"
        f"seeded={sorted(seeded_slots, key=lambda x: (x[0], x[1].value))}"
    )
