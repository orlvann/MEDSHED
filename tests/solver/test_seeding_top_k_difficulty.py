# tests/solver/test_seeding_top_k_difficulty.py
"""
Tests for seeding: "TOP K hardest slots by difficulty".

We test seeding directly (not via engine), because:
- TOP K difficulty is pure warm-start logic (hints),
- hints are NOT constraints, so engine/solver may ignore them,
- we want deterministic checks on which slots get hinted.

Rule recap (confirmed):
- Build candidate slots = all "in play" slots:
  * day in model.active_days
  * slot not ignored (not in model.ignore_slots)
  * slot key exists in model.allowed_slots
  excluding slots already seeded by head commitments.
- difficulty = len(model.allowed_slots[(day, shift_type)])
- Sort by (difficulty asc, day asc, shift_type asc)
- Seed TOP K slots where K = min(10, number_of_slots)
- Add exactly one "1" hint per seeded slot.
"""

from __future__ import annotations

import pytest

from backend.core import seeding
from backend.core.types import DoctorInput, PreferencesInput
from backend.models.common_enums import DoctorRole, ShiftType

pytestmark = [pytest.mark.solver]


def _seeded_slot_keys(hints: dict[tuple[int, int, ShiftType], int]) -> set[tuple[int, ShiftType]]:
    """
    Convert hint keys (day, doctor_id, shift_type) into slot keys (day, shift_type).

    We count only hints with value==1 (we ignore any future extensions).
    """
    out: set[tuple[int, ShiftType]] = set()
    for (day, _doc_id, shift_type), val in hints.items():
        if int(val) == 1:
            out.add((int(day), shift_type))
    return out


def test_top_k_difficulty_seeds_only_10_hardest_slots(make_hard_model, make_problem_data):
    """
    We create 12 distinct slots with strictly increasing difficulty 1..12.

    IMPORTANT:
    Here "difficulty" is defined as: len(allowed_candidates).
    So the "hardest" slots are those with the SMALLEST candidate lists.

    K = 10, so we expect:
    - exactly 10 seeded slots,
    - they are the 10 slots with smallest difficulty (1..10),
    - the 2 easiest slots (difficulty 11 and 12; most candidates) are NOT seeded.

    Also important:
    - We make the smallest doctor_id per slot UNIQUE to avoid
      "same doctor onsite+oncall same day" blocking any seed.
    """
    year = 2026
    month = 1
    days = [1, 2, 3, 4, 5, 6]  # 6 days -> 12 slots

    # Build allowed_slots with unique smallest doctor_id per slot.
    # Difficulty values 1..12 assigned in deterministic order:
    # (day=1 onsite)=1, (day=1 oncall)=2, ..., (day=6 oncall)=12
    allowed_slots: dict[tuple[int, ShiftType], list[int]] = {}
    doctors: dict[int, DoctorInput] = {}
    preferences: dict[int, PreferencesInput] = {}

    difficulty = 1
    for day in days:
        for shift_type in (ShiftType.onsite, ShiftType.oncall):
            # Unique smallest id per slot (deterministic seed pick).
            base_id = 1000 + day * 10 + (1 if shift_type == ShiftType.onsite else 2)

            # Make list length == difficulty.
            # base_id is the smallest candidate to keep pick deterministic.
            extra_ids = list(range(2000 + difficulty * 10, 2000 + difficulty * 10 + (difficulty - 1)))
            candidates = [base_id] + extra_ids
            allowed_slots[(day, shift_type)] = candidates

            # Register doctors + preferences for completeness.
            for doc_id in candidates:
                if doc_id not in doctors:
                    doctors[doc_id] = DoctorInput(id=int(doc_id), role=DoctorRole.resident, is_head=False)
                if doc_id not in preferences:
                    preferences[doc_id] = PreferencesInput(doctor_id=int(doc_id))

            difficulty += 1

    model = make_hard_model(
        year=year,
        month=month,
        days=days,
        active_days=days,
        doctors=doctors,
        preferences=preferences,
        participant_doctor_ids=set(doctors.keys()),
        ignore_days=set(),
        ignore_slots=set(),
        allowed_slots=allowed_slots,
    )

    # Use shared fixture (removes duplicated ProblemData boilerplate).
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
    seeded_slots = _seeded_slot_keys(hints)

    assert len(seeded_slots) == 10, (
        f"Expected exactly 10 seeded slots, got {len(seeded_slots)}.\n"
        f"seeded={sorted(seeded_slots, key=lambda x: (x[0], x[1].value))}"
    )

    # Expected slots are those with difficulties 1..10 only.
    # Because we assigned difficulty strictly increasing per slot, the expected set is deterministic.
    expected_slots: list[tuple[int, ShiftType]] = []
    difficulty = 1
    for day in days:
        for shift_type in (ShiftType.onsite, ShiftType.oncall):
            if difficulty <= 10:
                expected_slots.append((day, shift_type))
            difficulty += 1

    expected_set = set(expected_slots)

    assert seeded_slots == expected_set, (
        "Seeded slots do not match TOP K slots by smallest difficulty.\n"
        f"expected={sorted(expected_set, key=lambda x: (x[0], x[1].value))}\n"
        f"got={sorted(seeded_slots, key=lambda x: (x[0], x[1].value))}"
    )
