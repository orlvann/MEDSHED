from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Set, Tuple

from backend.core.fairness_expected import compute_expected_map_for_fairness
from backend.core.types import (
    DoctorCarryover,
    DoctorInput,
    HardModel,
    MonthCarryover,
    PreferencesInput,
    ProblemData,
)
from backend.models.common_enums import DoctorRole, ShiftType


def _weekday_map(year: int, month: int, days: List[int]) -> Dict[int, int]:
    """Build mapping: day_number -> weekday_index (0=Mon .. 6=Sun)."""
    return {int(d): datetime(int(year), int(month), int(d)).weekday() for d in days}


def _mk_problem_and_model(
    *,
    year: int,
    month: int,
    days: List[int],
    active_days: List[int],
    doctors: Dict[int, DoctorInput],
    preferences: Dict[int, PreferencesInput],
    participant_doctor_ids: Set[int],
    ignore_slots: Set[Tuple[int, ShiftType]],
    allowed_slots: Dict[Tuple[int, ShiftType], List[int]],
    carryover: MonthCarryover | None = None,
) -> Tuple[ProblemData, HardModel]:
    """
    Create ProblemData + HardModel for unit tests.

    NOTE:
    - These tests do NOT use OR-Tools.
    - HardModel here is just a container for the fairness calculator.
    """
    weekdays = _weekday_map(year, month, days)

    problem = ProblemData(
        year=year,
        month=month,
        days=list(days),
        weekdays=dict(weekdays),
        doctors=dict(doctors),
        preferences=dict(preferences),
        participant_doctor_ids=set(participant_doctor_ids),
        ignore_slots=set(ignore_slots),
        carryover=carryover,
    )

    model = HardModel(
        year=year,
        month=month,
        days=list(days),
        active_days=list(active_days),
        doctors=dict(doctors),
        preferences=dict(preferences),
        participant_doctor_ids=set(participant_doctor_ids),
        ignore_slots=set(ignore_slots),
        allowed_slots=dict(allowed_slots),
        seed_hints=None,
    )

    return problem, model


def _groups_from_doctors(doctors: Dict[int, DoctorInput], participants: Set[int]) -> Dict[str, List[int]]:
    """Match objective_builder grouping rule: specialists vs residents."""
    out = {"specialist": [], "resident": []}
    for did in sorted(participants):
        doc = doctors[int(did)]
        if doc.role == DoctorRole.specialist:
            out["specialist"].append(int(did))
        else:
            out["resident"].append(int(did))
    return out


def test_b0_demand_counts_only_required_slots_not_ignored():
    """
    B0:
    Demand R_* should ignore slots from ignore_slots.

    Setup:
    - Only specialists (no residents) => specialist targets == total demand.
    - active_days=[1,2]
    - ignore onsite on day 1 => onsite demand becomes 1 (only day 2).
    """
    year, month = 2026, 1
    days = [1, 2]
    active_days = [1, 2]

    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=False),
        2: DoctorInput(id=2, role=DoctorRole.specialist, is_head=False),
    }

    prefs = {1: PreferencesInput(doctor_id=1), 2: PreferencesInput(doctor_id=2)}

    ignore_slots = {(1, ShiftType.onsite)}  # only onsite day 1 ignored
    allowed_slots = {
        (1, ShiftType.onsite): [1, 2],
        (1, ShiftType.oncall): [1, 2],
        (2, ShiftType.onsite): [1, 2],
        (2, ShiftType.oncall): [1, 2],
    }

    problem, model = _mk_problem_and_model(
        year=year,
        month=month,
        days=days,
        active_days=active_days,
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_slots=ignore_slots,
        allowed_slots=allowed_slots,
        carryover=None,
    )

    groups = _groups_from_doctors(doctors, set(doctors.keys()))
    expected_map = compute_expected_map_for_fairness(model=model, problem=problem, group_to_doctors=groups)

    # With no residents, specialist expected should cover ALL demand.
    # Demand onsite_total = 1 (day2 only), oncall_total = 2 (day1+day2).
    onsite_sum = sum(expected_map.get((did, ShiftType.onsite, "onsite_weekday"), 0) for did in doctors.keys())
    onsite_sum += sum(expected_map.get((did, ShiftType.onsite, "onsite_weekend"), 0) for did in doctors.keys())

    oncall_sum = sum(expected_map.get((did, ShiftType.oncall, "oncall_weekday"), 0) for did in doctors.keys())
    oncall_sum += sum(expected_map.get((did, ShiftType.oncall, "oncall_weekend"), 0) for did in doctors.keys())

    assert onsite_sum == 1
    assert oncall_sum == 2


def test_b1_resident_caps_from_full_days_limit_resident_targets():
    """
    B1:
    Resident targets must be clamped by cap from FULL days (both shifts required).

    Setup:
    - 2 full days: [6,8] (both shifts required)
    - 1 resident, 1 specialist
    - Resident can do ONSITE only on ONE of the full days, and can do ONCALL on ZERO full days.
    - Proportional ideal might try to give resident some share, but cap must limit it:
        CAP_resident_onsite_total = 1
        CAP_resident_oncall_total = 0
    Expected:
    - resident expected onsite total (weekday+weekend) <= 1
    - resident expected oncall total (weekday+weekend) == 0
    """
    year, month = 2026, 1
    days = [6, 8]
    active_days = [6, 8]

    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=False),
        2: DoctorInput(id=2, role=DoctorRole.resident, is_head=False),
    }
    prefs = {1: PreferencesInput(doctor_id=1), 2: PreferencesInput(doctor_id=2)}

    # Allowed:
    # - Onsite: resident allowed only on day 6, not on day 8.
    # - Oncall: resident never allowed on full days.
    allowed_slots = {
        (6, ShiftType.onsite): [1, 2],
        (6, ShiftType.oncall): [1],  # resident not allowed
        (8, ShiftType.onsite): [1],  # resident not allowed
        (8, ShiftType.oncall): [1],  # resident not allowed
    }

    problem, model = _mk_problem_and_model(
        year=year,
        month=month,
        days=days,
        active_days=active_days,
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_slots=set(),
        allowed_slots=allowed_slots,
        carryover=None,
    )

    groups = _groups_from_doctors(doctors, set(doctors.keys()))
    expected_map = compute_expected_map_for_fairness(model=model, problem=problem, group_to_doctors=groups)

    resident_id = 2

    res_ons = expected_map.get((resident_id, ShiftType.onsite, "onsite_weekday"), 0) + expected_map.get(
        (resident_id, ShiftType.onsite, "onsite_weekend"), 0
    )
    res_onc = expected_map.get((resident_id, ShiftType.oncall, "oncall_weekday"), 0) + expected_map.get(
        (resident_id, ShiftType.oncall, "oncall_weekend"), 0
    )

    assert res_ons <= 1
    assert res_onc == 0


def test_b3_weekends_greater_than_total_is_fixed_by_raising_total_for_personal_targets():
    """
    B3 consistency fix:
    If personal target_weekends > personal target_total, we raise total to weekends.

    Setup:
    - 1 specialist with personal target_onsite_total=1, target_onsite_weekends=3
    - Month demand is big enough (R_total_limit and R_weekend_limit won't clamp it).
    Expected:
    - onsite_weekend expected == 3
    - onsite_weekday expected == 0 (because fixed_total=3, weekends=3)
    """
    year, month = 2026, 1
    days = [3, 10, 17, 24]  # Saturdays -> weekends
    active_days = list(days)

    doctors = {1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=False)}
    p = PreferencesInput(doctor_id=1)
    p.target_onsite_total = 1
    p.target_onsite_weekends = 3
    prefs = {1: p}

    allowed_slots = {(d, ShiftType.onsite): [1] for d in days}
    allowed_slots.update({(d, ShiftType.oncall): [1] for d in days})

    problem, model = _mk_problem_and_model(
        year=year,
        month=month,
        days=days,
        active_days=active_days,
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_slots=set(),
        allowed_slots=allowed_slots,
        carryover=None,
    )

    groups = _groups_from_doctors(doctors, set(doctors.keys()))
    expected_map = compute_expected_map_for_fairness(model=model, problem=problem, group_to_doctors=groups)

    assert expected_map[(1, ShiftType.onsite, "onsite_weekend")] == 3
    assert expected_map[(1, ShiftType.onsite, "onsite_weekday")] == 0


def test_b4_rotation_prioritizes_doctor_without_plus1_last_month():
    """
    B4 rotation:
    When rem=1, the +1 should go to the doctor who did NOT have +1 last month.

    Setup:
    - Two specialists, demand for onsite weekdays is 1
    - base=0, rem=1 => one doctor gets expected=1
    - carryover: doc1 had +1 last month => doc2 should get it now
    """
    year, month = 2026, 1
    days = [6]  # weekday
    active_days = [6]

    doctors = {
        1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=False),
        2: DoctorInput(id=2, role=DoctorRole.specialist, is_head=False),
    }
    prefs = {1: PreferencesInput(doctor_id=1), 2: PreferencesInput(doctor_id=2)}

    # Both allowed
    allowed_slots = {
        (6, ShiftType.onsite): [1, 2],
        (6, ShiftType.oncall): [1, 2],
    }

    carry = MonthCarryover(
        prev_year=2025,
        prev_month=12,
        per_doctor={
            1: DoctorCarryover(had_plus1_onsite_weekday_last=True),
            2: DoctorCarryover(had_plus1_onsite_weekday_last=False),
        },
    )

    # Ignore oncall so onsite demand is clean (1 required onsite, 0 required oncall)
    ignore_slots = {(6, ShiftType.oncall)}

    problem, model = _mk_problem_and_model(
        year=year,
        month=month,
        days=days,
        active_days=active_days,
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_slots=ignore_slots,
        allowed_slots=allowed_slots,
        carryover=carry,
    )

    groups = _groups_from_doctors(doctors, set(doctors.keys()))
    expected_map = compute_expected_map_for_fairness(model=model, problem=problem, group_to_doctors=groups)

    doc1 = expected_map.get((1, ShiftType.onsite, "onsite_weekday"), 0)
    doc2 = expected_map.get((2, ShiftType.onsite, "onsite_weekday"), 0)

    assert doc1 == 0
    assert doc2 == 1


def test_personal_target_is_trimmed_by_max_and_weekends_are_trimmed_and_consistent():
    """
    Personal target normalization:
    - max_total trims target_total
    - max_weekends trims target_weekends
    - then we ensure total >= weekends

    Setup:
    - target_total=10, max_total=4 -> total becomes 4
    - target_weekends=5, max_weekends=2 -> weekends becomes 2
    Expected:
    - expected_weekend=2
    - expected_weekday=2 (because total=4 and weekends=2)
    """
    year, month = 2026, 1
    days = [3, 4, 5, 6, 7, 8]  # mixed days, demand is large enough
    active_days = list(days)

    doctors = {1: DoctorInput(id=1, role=DoctorRole.specialist, is_head=False)}
    p = PreferencesInput(doctor_id=1)
    p.target_onsite_total = 10
    p.target_onsite_weekends = 5
    p.max_onsite_total = 4
    p.max_onsite_weekends = 2
    prefs = {1: p}

    allowed_slots = {(d, ShiftType.onsite): [1] for d in days}
    allowed_slots.update({(d, ShiftType.oncall): [1] for d in days})

    problem, model = _mk_problem_and_model(
        year=year,
        month=month,
        days=days,
        active_days=active_days,
        doctors=doctors,
        preferences=prefs,
        participant_doctor_ids=set(doctors.keys()),
        ignore_slots=set(),
        allowed_slots=allowed_slots,
        carryover=None,
    )

    groups = _groups_from_doctors(doctors, set(doctors.keys()))
    expected_map = compute_expected_map_for_fairness(model=model, problem=problem, group_to_doctors=groups)

    wknd = expected_map[(1, ShiftType.onsite, "onsite_weekend")]
    wd = expected_map[(1, ShiftType.onsite, "onsite_weekday")]

    assert wknd == 2
    assert wd == 2
