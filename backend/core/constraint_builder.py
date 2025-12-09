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

from typing import Any, List

from backend.models.common_enums import ShiftType

from .types import HardModel, ProblemData, Slot


def build_hard_model(problem: ProblemData, seed_hints: Any) -> HardModel:
    """
    Build the hard-constraint model structure.

    In this first step we only compute the list of allowed slots:
    - iterate over all days, shift types and participant doctors,
    - filter out globally ignored days and slots,
    - filter out doctor-level unavailable days from preferences.
    """

    allowed_slots: List[Slot] = []

    # Local reference for faster lookups.
    preferences_by_doctor = problem.preferences

    for day in problem.days:
        # Skip days that must be completely empty.
        if day in problem.ignore_days:
            continue

        # Iterate over all shift types (onsite / oncall).
        for shift_type in ShiftType:
            # Skip slots that admin explicitly wants to keep empty.
            if (day, shift_type) in problem.ignore_slots:
                continue

            for doctor_id in problem.participant_doctor_ids:
                prefs = preferences_by_doctor.get(doctor_id)

                # If we have preferences, apply unavailable-day filters.
                if prefs is not None:
                    # Treat onsite / on_duty as the same family.
                    if shift_type in (ShiftType.onsite, ShiftType.on_duty):
                        if day in prefs.unavailable_onsite_days:
                            # Doctor cannot work onsite on this day.
                            continue
                    # Treat oncall / on_call as the same family.
                    elif shift_type in (ShiftType.oncall, ShiftType.on_call):
                        if day in prefs.unavailable_oncall_days:
                            # Doctor cannot be on call on this day.
                            continue

                # If nothing blocked this combination, keep the slot.
                allowed_slots.append(Slot(day=day, shift_type=shift_type, doctor_id=doctor_id))

    return HardModel(problem=problem, allowed_slots=allowed_slots)
