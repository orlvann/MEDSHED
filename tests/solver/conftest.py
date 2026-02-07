# tests/solver/conftest.py
from __future__ import annotations

import inspect
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import pytest

from backend.core import constraint_builder
from backend.core.types import DoctorInput, HardModel, MonthCarryover, PreferencesInput
from backend.models.common_enums import DoctorRole, ShiftType


def _call_with_supported_kwargs(callable_obj: Any, kwargs: Dict[str, Any]) -> Any:
    """
    Call a function/class with only the kwargs it actually accepts.

    Why we need this:
    - Repo evolves (signatures change),
    - Tests sometimes pass extra knobs,
    - We still want to call REAL backend builders/classes.
    """
    sig = inspect.signature(callable_obj)
    accepted: Dict[str, Any] = {}
    for k, v in kwargs.items():
        if k in sig.parameters:
            accepted[k] = v
    return callable_obj(**accepted)


def _compute_weekdays(*, year: int, month: int, days: List[int]) -> Dict[int, int]:
    """
    Build mapping: day_number -> weekday_index (0=Mon ... 6=Sun).
    """
    out: Dict[int, int] = {}
    for d in days:
        out[int(d)] = datetime(int(year), int(month), int(d)).weekday()
    return out


def _problemdata_kwargs_with_aliases(
    *,
    year: int,
    month: int,
    days: List[int],
    active_days: List[int],
    weekdays: Dict[int, int],
    doctors: Dict[int, DoctorInput],
    preferences: Dict[int, PreferencesInput],
    participant_doctor_ids: Set[int],
    ignore_slots: Set[Tuple[int, ShiftType]],
    allowed_slots: Dict[Tuple[int, ShiftType], List[int]],
    carryover: Optional[MonthCarryover],
    required_slots: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Build kwargs for ProblemData with multiple possible parameter names.

    NOTE:
    Some repos keep allowed_slots INSIDE ProblemData,
    but other repos compute candidates later in build_hard_model().
    We still fill ProblemData defensively, but we ALSO pass allowed_slots
    directly into build_hard_model() (see make_hard_model).
    """
    return {
        # Identity
        "year": year,
        "month": month,
        # Days (aliases)
        "days": days,
        "day_numbers": days,
        "active_days": active_days,
        "active_day_numbers": active_days,
        # Weekdays mapping (aliases)
        "weekdays": weekdays,
        "weekday_by_day": weekdays,
        # Core inputs
        "doctors": doctors,
        "preferences": preferences,
        # Participants (aliases)
        "participant_doctor_ids": participant_doctor_ids,
        "participant_ids": participant_doctor_ids,
        "participants": participant_doctor_ids,
        # Ignore slots (aliases)
        "ignore_slots": ignore_slots,
        "ignored_slots": ignore_slots,
        # Allowed candidates per slot (aliases)
        "allowed_slots": allowed_slots,
        "allowed_by_slot": allowed_slots,
        "allowed_candidates": allowed_slots,
        "candidates_by_slot": allowed_slots,
        "slot_candidates": allowed_slots,
        # Required slots (aliases)
        "required_slots": required_slots,
        "required_shifts": required_slots,
        "required_by_day": required_slots,
        # Optional previous-month context (aliases)
        "carryover": carryover,
        "month_carryover": carryover,
        "prev_month_carryover": carryover,
        "previous_month": carryover,
    }


def _build_hard_model_kwargs_with_aliases(
    *,
    problem_data: Any,
    allowed_slots: Optional[Dict[Tuple[int, ShiftType], List[int]]],
    ignore_slots: Optional[Set[Tuple[int, ShiftType]]],
    participant_doctor_ids: Optional[Set[int]],
    required_slots: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Build kwargs for constraint_builder.build_hard_model(...) with aliases.

    This is the key fix for your remaining failures:
    In some repo versions, build_hard_model recomputes candidates unless
    allowed_slots is passed DIRECTLY as a function argument.
    """
    kwargs: Dict[str, Any] = {
        "problem": problem_data,
        "problem_data": problem_data,
    }

    # Pass-through only if caller provided them (important distinction):
    # - None means "let backend compute defaults"
    # - {} means "intentionally empty" (SolverStatus.EMPTY tests)
    if allowed_slots is not None:
        kwargs.update(
            {
                "allowed_slots": allowed_slots,
                "allowed_by_slot": allowed_slots,
                "allowed_candidates": allowed_slots,
                "candidates_by_slot": allowed_slots,
                "slot_candidates": allowed_slots,
            }
        )

    if ignore_slots is not None:
        kwargs.update(
            {
                "ignore_slots": ignore_slots,
                "ignored_slots": ignore_slots,
            }
        )

    if participant_doctor_ids is not None:
        kwargs.update(
            {
                "participant_doctor_ids": participant_doctor_ids,
                "participant_ids": participant_doctor_ids,
                "participants": participant_doctor_ids,
            }
        )

    if required_slots is not None:
        kwargs.update(
            {
                "required_slots": required_slots,
                "required_shifts": required_slots,
                "required_by_day": required_slots,
            }
        )

    return kwargs


@pytest.fixture()
def make_doctors() -> Callable[..., Dict[int, DoctorInput]]:
    """
    Factory fixture: create a small doctor dict for solver tests.
    Deterministic ids and roles.
    """

    def _make_doctors(
        *,
        num_specialists: int,
        num_residents: int,
        include_head: bool = False,
        start_id: int = 1,
    ) -> Dict[int, DoctorInput]:
        doctors: Dict[int, DoctorInput] = {}
        next_id = int(start_id)

        # Optional head specialist
        if include_head:
            doctors[next_id] = DoctorInput(id=next_id, role=DoctorRole.specialist, is_head=True)
            next_id += 1
            remaining_specialists = max(0, int(num_specialists) - 1)
        else:
            remaining_specialists = int(num_specialists)

        for _ in range(remaining_specialists):
            doctors[next_id] = DoctorInput(id=next_id, role=DoctorRole.specialist, is_head=False)
            next_id += 1

        for _ in range(int(num_residents)):
            doctors[next_id] = DoctorInput(id=next_id, role=DoctorRole.resident, is_head=False)
            next_id += 1

        return doctors

    return _make_doctors


@pytest.fixture()
def make_preferences() -> Callable[..., Dict[int, PreferencesInput]]:
    """
    Factory fixture: create PreferencesInput for doctors.

    Also sets weekend exception flag using multiple field-name variants.
    """

    def _make_preferences(
        *,
        doctors: Optional[Dict[int, DoctorInput]] = None,
        doctor_ids: Optional[List[int]] = None,
        unavailable_onsite_by_doc: Optional[Dict[int, List[int]]] = None,
        unavailable_oncall_by_doc: Optional[Dict[int, List[int]]] = None,
        allow_weekend_consecutive_by_doc: Optional[Dict[int, bool]] = None,
    ) -> Dict[int, PreferencesInput]:
        unavailable_onsite_by_doc = unavailable_onsite_by_doc or {}
        unavailable_oncall_by_doc = unavailable_oncall_by_doc or {}
        allow_weekend_consecutive_by_doc = allow_weekend_consecutive_by_doc or {}

        if doctors is not None:
            ids = list(doctors.keys())
        elif doctor_ids is not None:
            ids = list(doctor_ids)
        else:
            raise TypeError("make_preferences requires either doctors=... or doctor_ids=...")

        prefs: Dict[int, PreferencesInput] = {}

        for doc_id in ids:
            doc_id = int(doc_id)
            p = PreferencesInput(doctor_id=doc_id)

            if hasattr(p, "unavailable_onsite_days"):
                setattr(p, "unavailable_onsite_days", list(unavailable_onsite_by_doc.get(doc_id, [])))
            if hasattr(p, "unavailable_oncall_days"):
                setattr(p, "unavailable_oncall_days", list(unavailable_oncall_by_doc.get(doc_id, [])))

            flag_val = bool(allow_weekend_consecutive_by_doc.get(doc_id, False))

            # Weekend exception variants
            if hasattr(p, "allow_weekend_consecutive_onsite_oncall"):
                setattr(p, "allow_weekend_consecutive_onsite_oncall", flag_val)
            if hasattr(p, "allow_weekend_consecutive"):
                setattr(p, "allow_weekend_consecutive", flag_val)
            if hasattr(p, "allow_weekend_consecutive_days"):
                setattr(p, "allow_weekend_consecutive_days", flag_val)

            prefs[doc_id] = p

        return prefs

    return _make_preferences


@pytest.fixture()
def make_problem_data(make_doctors, make_preferences) -> Callable[..., Any]:
    """
    Build ProblemData using REAL repo code (defensive aliases).
    """

    def _make_problem_data(
        *,
        year: int = 2026,
        month: int = 1,
        days: Optional[List[int]] = None,
        active_days: Optional[List[int]] = None,
        doctors: Optional[Dict[int, DoctorInput]] = None,
        preferences: Optional[Dict[int, PreferencesInput]] = None,
        participant_doctor_ids: Optional[Set[int]] = None,
        ignore_slots: Optional[Set[Tuple[int, ShiftType]]] = None,
        allowed_slots: Optional[Dict[Tuple[int, ShiftType], List[int]]] = None,
        carryover: Optional[MonthCarryover] = None,
        required_slots: Optional[Dict[str, Any]] = None,
    ) -> Any:
        if days is None:
            days = [1, 2, 3]

        if active_days is None:
            active_days = list(days)

        if doctors is None:
            doctors = make_doctors(num_specialists=2, num_residents=1, include_head=False, start_id=1)

        assert doctors is not None

        if preferences is None:
            preferences = make_preferences(doctors=doctors)

        # Help static type checkers (Pylance): after this point, preferences is never None.
        assert preferences is not None
        prefs_typed: Dict[int, PreferencesInput] = preferences

        if participant_doctor_ids is None:
            participant_doctor_ids = set(doctors.keys())

        if ignore_slots is None:
            ignore_slots = set()

        # IMPORTANT: preserve empty dict {} if caller provided it.
        if allowed_slots is None:
            allowed_slots = {}
            for d in days:
                allowed_slots[(d, ShiftType.onsite)] = list(participant_doctor_ids)
                allowed_slots[(d, ShiftType.oncall)] = list(participant_doctor_ids)

        weekdays = _compute_weekdays(year=year, month=month, days=list(days))

        kwargs = _problemdata_kwargs_with_aliases(
            year=year,
            month=month,
            days=list(days),
            active_days=list(active_days),
            weekdays=weekdays,
            doctors=doctors,
            preferences=prefs_typed,
            participant_doctor_ids=set(participant_doctor_ids),
            ignore_slots=set(ignore_slots),
            allowed_slots=dict(allowed_slots),
            carryover=carryover,
            required_slots=required_slots,
        )

        return _call_with_supported_kwargs(constraint_builder.ProblemData, kwargs)

    return _make_problem_data


@pytest.fixture()
def make_hard_model(make_problem_data) -> Callable[..., Any]:
    """
    Build HardModel for tests.

    IMPORTANT:
    In this repo, constraint_builder.build_hard_model() ALWAYS recomputes allowed_slots
    from participants + ignore_slots + unavailable_* preferences.

    Many solver tests need to CONTROL allowed_slots directly (including allowed_slots={}).
    So:
    - if allowed_slots is provided (even empty dict), we build HardModel directly,
    - otherwise we call the real constraint_builder.build_hard_model(problem).
    """

    def _compute_active_days(days_list: List[int], ignore: Set[Tuple[int, ShiftType]]) -> List[int]:
        """
        Match repo policy:
        - A day is excluded from active_days ONLY if BOTH slots are ignored.
        """
        out: List[int] = []
        for d in days_list:
            both_ignored = (d, ShiftType.onsite) in ignore and (d, ShiftType.oncall) in ignore
            if both_ignored:
                continue
            out.append(d)
        return out

    def _make_hard_model(
        *,
        year: int = 2026,
        month: int = 1,
        days: Optional[List[int]] = None,
        active_days: Optional[List[int]] = None,
        doctors: Optional[Dict[int, DoctorInput]] = None,
        preferences: Optional[Dict[int, PreferencesInput]] = None,
        participant_doctor_ids: Optional[Set[int]] = None,
        ignore_slots: Optional[Set[Tuple[int, ShiftType]]] = None,
        allowed_slots: Optional[Dict[Tuple[int, ShiftType], List[int]]] = None,
        carryover: Optional[MonthCarryover] = None,
        required_slots: Optional[Dict[str, Any]] = None,
    ) -> Any:
        # Still reuse ProblemData builder (real repo structure, weekdays, etc.)
        problem_data = make_problem_data(
            year=year,
            month=month,
            days=days,
            active_days=active_days,
            doctors=doctors,
            preferences=preferences,
            participant_doctor_ids=participant_doctor_ids,
            ignore_slots=ignore_slots,
            allowed_slots=allowed_slots,
            carryover=carryover,
            required_slots=required_slots,
        )

        # KEY BEHAVIOR:
        # If tests pass allowed_slots (even {}), do NOT call constraint_builder.build_hard_model(),
        # because it will overwrite candidates and break test setups.
        if allowed_slots is not None:
            days_list = list(getattr(problem_data, "days"))
            ignore = set(ignore_slots) if ignore_slots is not None else set(getattr(problem_data, "ignore_slots"))
            participants = (
                set(participant_doctor_ids)
                if participant_doctor_ids is not None
                else set(getattr(problem_data, "participant_doctor_ids"))
            )

            if active_days is not None:
                active_days_list = list(active_days)
            else:
                active_days_list = _compute_active_days(days_list, ignore)

            hard_kwargs: Dict[str, Any] = {
                "year": int(getattr(problem_data, "year")),
                "month": int(getattr(problem_data, "month")),
                "days": days_list,
                "active_days": active_days_list,
                "doctors": dict(getattr(problem_data, "doctors")),
                "preferences": dict(getattr(problem_data, "preferences")),
                "participant_doctor_ids": participants,
                "ignore_slots": ignore,
                "allowed_slots": dict(allowed_slots),  # EXACTLY as test provided (can be empty)
                "seed_hints": None,
                # carryover may or may not exist on HardModel depending on repo version
                "carryover": getattr(problem_data, "carryover", None),
            }

            return _call_with_supported_kwargs(HardModel, hard_kwargs)

        # Default path: use real builder (repo computes candidates itself)
        return constraint_builder.build_hard_model(problem_data)

    return _make_hard_model
