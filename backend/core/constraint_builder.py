# backend/core/constraint_builder.py
"""
Build the hard-constraint part of the model (no objective yet).

This module:
- defines decision variables,
- enforces all hard rules:
  * 1 onsite + 1 oncall per day,
  * at least one specialist per day,
  * no double-role per day per doctor,
  * no assignments on unavailable days,
  * ignore_days / ignore_slots.
"""

from typing import Any, Dict, List, Tuple

from backend.models.common_enums import ShiftType

from .types import HardModel, PreferencesInput, ProblemData


def build_hard_model(problem: ProblemData, seed_hints: Any) -> HardModel:
    """
    Build a HardModel from ProblemData.

    ```
    In this stage we only compute allowed_slots:
    - skip whole days from ignore_days,
    - skip specific (day, shift_type) from ignore_slots,
    - exclude doctors who are unavailable for a given shift type on a given day.

    The result is a dict:
        allowed_slots[(day, shift_type)] = [doctor_id, doctor_id, ...]
    """

    # Build a safe preferences mapping for all participants.
    # If a doctor has no preferences, treat it as "empty" (no unavailable days).
    prefs_by_doctor: Dict[int, PreferencesInput] = {}
    for doctor_id in problem.participant_doctor_ids:
        prefs_by_doctor[doctor_id] = problem.preferences.get(doctor_id, PreferencesInput(doctor_id=doctor_id))

    allowed_slots: Dict[Tuple[int, ShiftType], List[int]] = {}

    # Active days = days that solver must actually schedule.
    # Exclude:
    # - ignore_days (whole day ignored),
    # - days where BOTH shifts are ignored via ignore_slots (day effectively empty).
    active_days: List[int] = []
    for day in problem.days:
        if day in problem.ignore_days:
            continue

        both_ignored = (day, ShiftType.onsite) in problem.ignore_slots and (
            day,
            ShiftType.oncall,
        ) in problem.ignore_slots
        if both_ignored:
            continue

        active_days.append(day)

    for day in active_days:
        # We only consider the two shift types used by the schedule.
        for shift_type in (ShiftType.onsite, ShiftType.oncall):
            # Skip slots that admin explicitly wants to keep empty.
            if (day, shift_type) in problem.ignore_slots:
                continue

            allowed: List[int] = []

            for doctor_id in problem.participant_doctor_ids:
                prefs = prefs_by_doctor.get(doctor_id)

                # Apply unavailable-day filters.
                if shift_type == ShiftType.onsite:
                    if prefs and day in prefs.unavailable_onsite_days:
                        continue
                else:  # ShiftType.oncall
                    if prefs and day in prefs.unavailable_oncall_days:
                        continue

                allowed.append(doctor_id)

            # Keep the key even if the list is empty (it helps diagnostics later).
            # Optional: sort for deterministic behavior.
            allowed_slots[(day, shift_type)] = sorted(allowed)

    return HardModel(
        year=problem.year,
        month=problem.month,
        days=list(problem.days),
        active_days=list(active_days),
        doctors=dict(problem.doctors),
        preferences=dict(problem.preferences),
        participant_doctor_ids=set(problem.participant_doctor_ids),
        ignore_days=set(problem.ignore_days),
        ignore_slots=set(problem.ignore_slots),
        allowed_slots=allowed_slots,
        seed_hints=seed_hints,
    )
