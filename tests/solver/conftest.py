# tests/solver.conftest.py
"""
Pytest fixtures for solver tests.

We define fixtures here so tests can focus on "what is being tested",
not on building long HardModel objects each time.

This file contains:

* small "building blocks" fixtures (single doctors),
* factory fixtures that return functions: make_doctors / make_preferences / make_hard_model.

IMPORTANT design goals:

* deterministic IDs and ordering (stable tests),
* no DB / no FastAPI / no SQLAlchemy imports,
* behavior aligned with production constraint_builder.build_hard_model for active_days.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Set, Tuple

import pytest

from backend.core.types import DoctorInput, HardModel, PreferencesInput
from backend.models.common_enums import DoctorRole, ShiftType

# Small constants (optional, but helpful in tests)

DEFAULT_YEAR: int = 2026
DEFAULT_MONTH: int = 1

# ---------------------------

# 1) Simple "building block" doctor fixtures

# ---------------------------


@pytest.fixture()
def doctor_specialist() -> DoctorInput:
    """
    Minimal specialist doctor used in many tests.

    ```
    Fixed ID=1 so it is stable across the test suite.
    """
    return DoctorInput(id=1, role=DoctorRole.specialist, is_head=False)


@pytest.fixture()
def doctor_resident() -> DoctorInput:
    """
    Minimal resident doctor used in many tests.

    ```
    Fixed ID=2 so it is stable across the test suite.
    """
    return DoctorInput(id=2, role=DoctorRole.resident, is_head=False)


@pytest.fixture()
def doctor_head_specialist() -> DoctorInput:
    """
    Optional but very useful: a specialist who is also a head.

    ```
    Fixed ID=10 so it is easy to spot in logs and assertions.
    """
    return DoctorInput(id=10, role=DoctorRole.specialist, is_head=True)


# ---------------------------

# 2) make_doctors() factory fixture

# ---------------------------


@pytest.fixture()
def make_doctors() -> Callable[..., Dict[int, DoctorInput]]:
    """
    Factory fixture that returns a function building a deterministic doctors dict.

    ```
    Usage idea in tests:
        doctors = make_doctors(num_specialists=2, num_residents=1, include_head=True, start_id=100)

    Returned dict format:
        {doctor_id: DoctorInput(...), ...}
    """

    def _make_doctors(
        *,
        num_specialists: int = 1,
        num_residents: int = 1,
        include_head: bool = False,
        start_id: int = 1,
    ) -> Dict[int, DoctorInput]:
        # Defensive: keep tests predictable and avoid silent weirdness.
        if num_specialists < 0:
            raise ValueError("num_specialists must be >= 0")
        if num_residents < 0:
            raise ValueError("num_residents must be >= 0")
        if start_id < 1:
            raise ValueError("start_id must be >= 1")

        doctors: Dict[int, DoctorInput] = {}

        next_id = int(start_id)

        # Specialists first (stable ordering)
        for _ in range(int(num_specialists)):
            doctors[next_id] = DoctorInput(id=next_id, role=DoctorRole.specialist, is_head=False)
            next_id += 1

        # Residents next
        for _ in range(int(num_residents)):
            doctors[next_id] = DoctorInput(id=next_id, role=DoctorRole.resident, is_head=False)
            next_id += 1

        # Optional head (always a separate doctor)
        if include_head:
            doctors[next_id] = DoctorInput(id=next_id, role=DoctorRole.specialist, is_head=True)
            next_id += 1

        return doctors

    return _make_doctors


# ---------------------------

# 3) make_preferences() factory fixture

# ---------------------------


@pytest.fixture()
def make_preferences() -> Callable[..., Dict[int, PreferencesInput]]:
    """
    Factory fixture that returns a function building a preferences dict.

    ```
    Defaults:
    - "all available" (no unavailable days),
    - allow_weekend_consecutive_onsite_oncall defaults to False.

    You can override per doctor via dict parameters.
    """

    def _make_preferences(
        *,
        doctors: Dict[int, DoctorInput] | None = None,
        doctor_ids: List[int] | None = None,
        allow_weekend_consecutive_by_doc: Dict[int, bool] | None = None,
        unavailable_onsite_by_doc: Dict[int, List[int]] | None = None,
        unavailable_oncall_by_doc: Dict[int, List[int]] | None = None,
    ) -> Dict[int, PreferencesInput]:
        # Determine which doctor IDs to build preferences for.
        if doctor_ids is None:
            if doctors is None:
                raise ValueError("make_preferences: provide either doctor_ids or doctors")
            chosen_ids = list(doctors.keys())
        else:
            chosen_ids = list(doctor_ids)

        # Defensive normalization for optional dict inputs.
        allow_weekend_consecutive_by_doc = allow_weekend_consecutive_by_doc or {}
        unavailable_onsite_by_doc = unavailable_onsite_by_doc or {}
        unavailable_oncall_by_doc = unavailable_oncall_by_doc or {}

        prefs: Dict[int, PreferencesInput] = {}

        for doc_id in chosen_ids:
            prefs[doc_id] = PreferencesInput(
                doctor_id=int(doc_id),
                # "all available" default => empty lists
                unavailable_onsite_days=list(unavailable_onsite_by_doc.get(doc_id, [])),
                unavailable_oncall_days=list(unavailable_oncall_by_doc.get(doc_id, [])),
                allow_weekend_consecutive_onsite_oncall=bool(allow_weekend_consecutive_by_doc.get(doc_id, False)),
            )

        return prefs

    return _make_preferences


# ---------------------------

# 4) make_hard_model() factory fixture (most important)

# ---------------------------


@pytest.fixture()
def make_hard_model(
    make_doctors: Callable[..., Dict[int, DoctorInput]],
    make_preferences: Callable[..., Dict[int, PreferencesInput]],
) -> Callable[..., HardModel]:
    """
    Factory fixture that returns a function building a HardModel without DB.

    ```
    IMPORTANT:
    - This does NOT build ProblemData.
    - This does NOT compute weekdays.
    - It focuses on HardModel fields used directly by the solver engine.

    active_days logic matches backend/core/constraint_builder.py:
    - exclude ignore_days,
    - exclude days where BOTH shifts are ignored via ignore_slots.
    """

    def _compute_active_days_like_production(
        *, days: List[int], ignore_days: Set[int], ignore_slots: Set[Tuple[int, ShiftType]]
    ) -> List[int]:
        active: List[int] = []
        for day in list(days):
            d = int(day)

            if d in ignore_days:
                continue

            both_ignored = (d, ShiftType.onsite) in ignore_slots and (d, ShiftType.oncall) in ignore_slots
            if both_ignored:
                continue
            active.append(d)
        return active

    def _build_default_allowed_slots(
        *,
        active_days: List[int],
        participant_doctor_ids: Set[int],
        ignore_slots: Set[Tuple[int, ShiftType]],
    ) -> Dict[Tuple[int, ShiftType], List[int]]:
        """
        Build a simple default allowed_slots mapping.

        We keep production-like behavior:
        - if a slot is ignored, we SKIP creating the key completely (same as constraint_builder),
        - otherwise, everyone in participant_doctor_ids is allowed.

        NOTE:
        Tests can still explicitly pass:
        - allowed_slots={} to trigger EMPTY,
        - or keys with empty lists to trigger INFEASIBLE.
        """
        allowed: Dict[Tuple[int, ShiftType], List[int]] = {}
        candidates_sorted = sorted(int(x) for x in participant_doctor_ids)

        for day in active_days:
            for shift in (ShiftType.onsite, ShiftType.oncall):
                if (int(day), shift) in ignore_slots:
                    continue
                allowed[(int(day), shift)] = list(candidates_sorted)

        return allowed

    def _make_hard_model(
        *,
        year: int = DEFAULT_YEAR,
        month: int = DEFAULT_MONTH,
        days: List[int] | None = None,
        doctors: Dict[int, DoctorInput] | None = None,
        preferences: Dict[int, PreferencesInput] | None = None,
        participant_doctor_ids: Set[int] | None = None,
        ignore_days: Set[int] | None = None,
        ignore_slots: Set[Tuple[int, ShiftType]] | None = None,
        active_days: List[int] | None = None,
        allowed_slots: Dict[Tuple[int, ShiftType], List[int]] | None = None,
    ) -> HardModel:
        # Defaults for "tiny model" tests
        if days is None:
            days = [1, 2, 3]

        if doctors is None:
            doctors = make_doctors(num_specialists=1, num_residents=1, include_head=False, start_id=1)

        if participant_doctor_ids is None:
            participant_doctor_ids = set(doctors.keys())

        if ignore_days is None:
            ignore_days = set()

        if ignore_slots is None:
            ignore_slots = set()

        # Preferences default to "all available"
        if preferences is None:
            preferences = make_preferences(doctors=doctors)

        # active_days default computed like production, unless explicitly provided
        if active_days is None:
            active_days = _compute_active_days_like_production(
                days=list(days),
                ignore_days=set(ignore_days),
                ignore_slots=set(ignore_slots),
            )

        # allowed_slots default: everyone can work everywhere on active_days
        # (production-like behavior: ignored slots are skipped)
        if allowed_slots is None:
            allowed_slots = _build_default_allowed_slots(
                active_days=list(active_days),
                participant_doctor_ids=set(participant_doctor_ids),
                ignore_slots=set(ignore_slots),
            )

        return HardModel(
            year=int(year),
            month=int(month),
            days=list(int(d) for d in days),
            active_days=list(int(d) for d in active_days),
            doctors=dict(doctors),
            preferences=dict(preferences),
            participant_doctor_ids=set(int(x) for x in participant_doctor_ids),
            ignore_days=set(int(d) for d in ignore_days),
            ignore_slots=set((int(d), s) for (d, s) in ignore_slots),
            allowed_slots=dict(allowed_slots),
            seed_hints=None,
        )

    return _make_hard_model
