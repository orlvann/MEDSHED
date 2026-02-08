# backend/core/constraint_builder.py
"""
Build the hard-constraint part of the model (no objective yet).

This module:
- precomputes allowed_slots,
- enforces all hard rules:
  * 1 onsite + 1 oncall per day,
  * at least one specialist per day,
  * no double-role per day per doctor,
  * no assignments on unavailable days,
  * ignore_slots only (slot-level ignore).
"""

from typing import Any, Dict, List, Tuple

from backend.models.common_enums import ShiftType

from .types import HardModel, PreferencesInput, ProblemData


def build_hard_model(problem: ProblemData, seed_hints: Any | None = None) -> HardModel:
    """
    Build a HardModel from ProblemData.

    ```
    In this stage we only compute allowed_slots:
    - skip whole days ONLY when BOTH slots are ignored via ignore_slots,
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
    # - days where BOTH shifts are ignored via ignore_slots (day effectively empty).
    active_days: List[int] = []
    for day in problem.days:
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
        ignore_slots=set(problem.ignore_slots),
        allowed_slots=allowed_slots,
        seed_hints=seed_hints,
        carryover=problem.carryover,
    )


def build_hard_model_for_diagnostics(problem: ProblemData, seed_hints: Any | None = None) -> HardModel:
    """
    Build a HardModel for DIAGNOSTICS (variant B):

    Goals:
    - Fairness should be feasibility-aware (use unavailable filters via allowed_slots).
    - Ignore markers MUST NOT improve metrics (a gap is still a gap),
      so diagnostics fairness must treat the whole month as required.

    Policy:
    - active_days = ALL problem.days (full month)
    - ignore_slots = empty set (so expected demand is "full month required")
    - allowed_slots are computed for ALL days and BOTH shift types,
      filtering only by unavailable_* days (same as solver feasibility logic),
      but NOT skipping ignored slots.

    This model is used only by diagnostics (pure core) and does not affect solving.
    """

    # Build a safe preferences mapping for all participants.
    # If a doctor has no preferences, treat it as "empty" (no unavailable days).
    prefs_by_doctor: Dict[int, PreferencesInput] = {}
    for doctor_id in problem.participant_doctor_ids:
        prefs_by_doctor[doctor_id] = problem.preferences.get(doctor_id, PreferencesInput(doctor_id=doctor_id))

    allowed_slots: Dict[Tuple[int, ShiftType], List[int]] = {}

    # DIAGNOSTICS: active days are always the full month.
    active_days: List[int] = [int(d) for d in problem.days]

    for day in active_days:
        for shift_type in (ShiftType.onsite, ShiftType.oncall):
            allowed: List[int] = []

            for doctor_id in problem.participant_doctor_ids:
                prefs = prefs_by_doctor.get(int(doctor_id))

                # Apply unavailable-day filters (feasibility-aware).
                if shift_type == ShiftType.onsite:
                    if prefs and day in (prefs.unavailable_onsite_days or []):
                        continue
                else:  # ShiftType.oncall
                    if prefs and day in (prefs.unavailable_oncall_days or []):
                        continue

                allowed.append(int(doctor_id))

            # Keep the key even if the list is empty (helps diagnostics later).
            allowed_slots[(int(day), shift_type)] = sorted(allowed)

    return HardModel(
        year=int(problem.year),
        month=int(problem.month),
        days=[int(d) for d in problem.days],
        active_days=list(active_days),
        doctors=dict(problem.doctors),
        preferences=dict(problem.preferences),
        participant_doctor_ids=set(int(d) for d in problem.participant_doctor_ids),
        # IMPORTANT (variant B):
        # ignore markers must NOT shrink required scope for diagnostics metrics.
        ignore_slots=set(),
        allowed_slots=allowed_slots,
        seed_hints=seed_hints,
        carryover=problem.carryover,
    )
