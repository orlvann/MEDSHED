from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Tuple

from backend.core.fairness_expected_edit import compute_expected_map_for_fairness_edit
from backend.core.types import (
    DoctorCarryover,
    DoctorInput,
    HardModel,
    MonthCarryover,
    PreferencesInput,
    ProblemData,
)
from backend.models.common_enums import DoctorRole, ShiftType

ExpectedKey = Tuple[int, ShiftType, str]  # (doctor_id, shift_type, category_name)


def _weekdays_map(year: int, month: int, days: List[int]) -> Dict[int, int]:
    """Build mapping: day -> weekday (0=Mon .. 6=Sun)."""
    return {int(d): int(datetime(int(year), int(month), int(d)).weekday()) for d in days}


def _make_doctors(*, resident_ids: List[int], specialist_ids: List[int]) -> Dict[int, DoctorInput]:
    """Create DoctorInput dict."""
    out: Dict[int, DoctorInput] = {}
    for did in resident_ids:
        out[int(did)] = DoctorInput(id=int(did), role=DoctorRole.resident, is_head=False, is_active=True)
    for did in specialist_ids:
        out[int(did)] = DoctorInput(id=int(did), role=DoctorRole.specialist, is_head=False, is_active=True)
    return out


def _make_prefs(*, doctor_ids: List[int]) -> Dict[int, PreferencesInput]:
    """Create empty PreferencesInput dict (no personal targets unless test sets them)."""
    return {int(did): PreferencesInput(doctor_id=int(did)) for did in doctor_ids}


def _make_problem_and_model(
    *,
    year: int,
    month: int,
    days: List[int],
    resident_ids: List[int],
    specialist_ids: List[int],
    carryover: MonthCarryover | None = None,
    preferences_override: Dict[int, PreferencesInput] | None = None,
) -> tuple[ProblemData, HardModel, Dict[str, List[int]]]:
    """
    Build ProblemData + HardModel for tests.

    Note:
    - For edit-mode helper, allowed_slots should NOT matter,
      but we still provide allowed_slots={} to keep HardModel complete.
    """
    doctors = _make_doctors(resident_ids=resident_ids, specialist_ids=specialist_ids)

    all_ids = sorted([*resident_ids, *specialist_ids])
    prefs = preferences_override or _make_prefs(doctor_ids=all_ids)

    problem = ProblemData(
        year=int(year),
        month=int(month),
        days=[int(d) for d in days],
        weekdays=_weekdays_map(year, month, days),
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(int(x) for x in all_ids),
        ignore_slots=set(),
        carryover=carryover,
    )

    model = HardModel(
        year=int(year),
        month=int(month),
        days=[int(d) for d in days],
        active_days=[int(d) for d in days],
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(int(x) for x in all_ids),
        ignore_slots=set(),
        carryover=carryover,
        allowed_slots={},  # edit-mode expected should not use this
        seed_hints=None,
    )

    group_to_doctors = {"resident": [int(x) for x in resident_ids], "specialist": [int(x) for x in specialist_ids]}
    return problem, model, group_to_doctors


def _sum_expected_all_categories(expected: Dict[ExpectedKey, int], doctor_ids: List[int]) -> int:
    """Sum expected across all 4 categories for the given doctor ids."""
    total = 0
    for did in doctor_ids:
        total += int(expected.get((int(did), ShiftType.onsite, "onsite_weekend"), 0))
        total += int(expected.get((int(did), ShiftType.onsite, "onsite_weekday"), 0))
        total += int(expected.get((int(did), ShiftType.oncall, "oncall_weekend"), 0))
        total += int(expected.get((int(did), ShiftType.oncall, "oncall_weekday"), 0))
    return int(total)


def _sum_expected_for_shift(expected: Dict[ExpectedKey, int], doctor_ids: List[int], shift: ShiftType) -> int:
    """Sum expected for one shift type across the two categories (weekend + weekday)."""
    total = 0
    if shift == ShiftType.onsite:
        for did in doctor_ids:
            total += int(expected.get((int(did), shift, "onsite_weekend"), 0))
            total += int(expected.get((int(did), shift, "onsite_weekday"), 0))
    else:
        for did in doctor_ids:
            total += int(expected.get((int(did), shift, "oncall_weekend"), 0))
            total += int(expected.get((int(did), shift, "oncall_weekday"), 0))
    return int(total)


def test_edit_cap_residents_equals_number_of_days() -> None:
    """
    cap rezydentów = liczba dni (edit policy).

    Setup:
    - 10 dni => 20 slotów (onsite + oncall)
    - 3 rezydentów, 1 specjalista => share_res = 3/4
    - ideal resident share: round(20 * 0.75) = 15
    - cap = days = 10 => resident expected total (all categories) must be 10
    """
    days = list(range(1, 11))  # 10 days
    residents = [1, 2, 3]
    specialists = [10]

    problem, model, group_to_doctors = _make_problem_and_model(
        year=2026,
        month=2,
        days=days,
        resident_ids=residents,
        specialist_ids=specialists,
        carryover=None,
    )

    expected = compute_expected_map_for_fairness_edit(model=model, problem=problem, group_to_doctors=group_to_doctors)

    assert _sum_expected_all_categories(expected, residents) == 10


def test_edit_split_onsite_oncall_when_demands_equal() -> None:
    """
    split onsite/oncall:

    For a normal month segment where onsite_total == oncall_total,
    and resident total is known (cap), the split should be 50/50 in aggregate.

    Using the same setup:
    - days = 10 => cap resident = 10
    - onsite demand = 10, oncall demand = 10 => resident split should be 5 + 5
    """
    days = list(range(1, 11))
    residents = [1, 2, 3]
    specialists = [10]

    problem, model, group_to_doctors = _make_problem_and_model(
        year=2026,
        month=2,
        days=days,
        resident_ids=residents,
        specialist_ids=specialists,
        carryover=None,
    )

    expected = compute_expected_map_for_fairness_edit(model=model, problem=problem, group_to_doctors=group_to_doctors)

    assert _sum_expected_for_shift(expected, residents, ShiftType.onsite) == 5
    assert _sum_expected_for_shift(expected, residents, ShiftType.oncall) == 5


def test_edit_personal_targets_weekend_greater_than_total_fix() -> None:
    """
    weekend>total fix for personal targets:

    If doctor has:
      target_onsite_total = 2
      target_onsite_weekends = 4
    we must normalize so that:
      expected_onsite_weekend = 4
      expected_onsite_weekday = 0
    (because total must be >= weekends)
    """
    # Any days list is OK; we just need enough weekends possible.
    days = list(range(1, 15))
    residents = [1]
    specialists = [10]

    prefs = _make_prefs(doctor_ids=[1, 10])
    prefs[1].target_onsite_total = 2
    prefs[1].target_onsite_weekends = 4

    problem, model, group_to_doctors = _make_problem_and_model(
        year=2026,
        month=2,
        days=days,
        resident_ids=residents,
        specialist_ids=specialists,
        carryover=None,
        preferences_override=prefs,
    )

    expected = compute_expected_map_for_fairness_edit(model=model, problem=problem, group_to_doctors=group_to_doctors)

    assert expected[(1, ShiftType.onsite, "onsite_weekend")] == 4
    assert expected[(1, ShiftType.onsite, "onsite_weekday")] == 0


def test_edit_plus_one_rotation_uses_carryover_flags() -> None:
    """
    Rotacja +1 z carryover.

    Chcemy sytuację:
    - 2 rezydentów, 1 specjalista
    - target dla kategorii 'onsite_weekend' wśród rezydentów = 1
      => base=0 rem=1 => dokładnie jedna osoba dostaje +1
    - jeśli doc1 miał had_plus1_onsite_weekend_last=True, to doc2 ma dostać +1 teraz.

    Konkretny kalendarz:
    - Feb 2026: day 1 = Sunday (weekend), day 2 = Monday (weekday)
    - days=[1,2] => onsite_weekends = 1, onsite_total = 2
    """
    days = [1, 2]
    residents = [1, 2]
    specialists = [10]

    carryover = MonthCarryover(
        prev_year=2026,
        prev_month=1,
        per_doctor={
            1: DoctorCarryover(had_plus1_onsite_weekend_last=True),
            2: DoctorCarryover(had_plus1_onsite_weekend_last=False),
            10: DoctorCarryover(),
        },
    )

    problem, model, group_to_doctors = _make_problem_and_model(
        year=2026,
        month=2,
        days=days,
        resident_ids=residents,
        specialist_ids=specialists,
        carryover=carryover,
    )

    expected = compute_expected_map_for_fairness_edit(model=model, problem=problem, group_to_doctors=group_to_doctors)

    v1 = int(expected.get((1, ShiftType.onsite, "onsite_weekend"), 0))
    v2 = int(expected.get((2, ShiftType.onsite, "onsite_weekend"), 0))

    assert v1 == 0
    assert v2 == 1
