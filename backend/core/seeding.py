# backend/core/seeding.py
"""
Warm-start / seeding logic for the solver.

This module produces "hints" for the solver:
- suggested assignments for heads on their preferred days,
- initial coverage for hardest slots (few available doctors),
- weekend combos for doctors who allow consecutive onsite+oncall.

For MVP it can return an empty structure.
"""

from datetime import datetime
from typing import Dict, List, Tuple

from backend.models.common_enums import DoctorRole, ShiftType

from .types import HardModel, ProblemData

SeedHintKey = Tuple[int, int, ShiftType]  # (day, doctor_id, shift_type)


def generate_initial_hints(model: HardModel, problem: ProblemData) -> Dict[SeedHintKey, int]:
    """
    Build a simple warm-start for CP-SAT solver.

    ```
    Idea (MVP):
    - Prefer "difficult" or important slots:
        * weekends (Sat/Sun),
        * heads and specialists,
        * strong preferred concrete days.
    - Respect hard availability via model.allowed_slots.
    - Do NOT enforce anything: these are only hints for solver.SetHint.

    Returns:
        Dict mapping (day, doctor_id, shift_type) -> 0/1
        (1 = suggested assignment).
    """
    hints: Dict[SeedHintKey, int] = {}

    # Track which doctor is already hinted for a given day,
    # so we do not seed onsite+oncall for the same doctor on the same day.
    # Example: chosen_by_day[day]["onsite"] = doctor_id
    chosen_by_day: Dict[int, Dict[str, int]] = {}

    def _weekday(day: int) -> int:
        # 0=Mon .. 6=Sun (pure date, no timezone logic)
        return datetime(model.year, model.month, day).weekday()

    def _allowed(day: int, shift_type: ShiftType) -> List[int]:
        # If slot does not exist -> no candidates.
        return list(model.allowed_slots.get((day, shift_type), []))

    def _is_head(doc_id: int) -> bool:
        doc = model.doctors.get(doc_id)
        return bool(doc and doc.is_head)

    def _is_specialist(doc_id: int) -> bool:
        doc = model.doctors.get(doc_id)
        return bool(doc and doc.role == DoctorRole.specialist)

    def _prefers_day(doc_id: int, shift_type: ShiftType, day: int) -> bool:
        pref = model.preferences.get(doc_id)
        if pref is None:
            return False
        if shift_type == ShiftType.onsite:
            return day in pref.preferred_onsite_days
        return day in pref.preferred_oncall_days

    def _pick_one(candidates: List[int]) -> int | None:
        # Deterministic: pick the smallest doctor_id.
        if not candidates:
            return None
        return sorted(candidates)[0]

    def _set_day_choice(day: int, shift_type: ShiftType, doctor_id: int) -> None:
        # Store the hint (1) and remember the choice for "no double shift" seeding.
        hints[(day, doctor_id, shift_type)] = 1
        chosen_by_day.setdefault(day, {})
        chosen_by_day[day][shift_type.value] = doctor_id

    def _already_seeded_same_day(day: int, doctor_id: int) -> bool:
        # Prevent seeding doc as both onsite and oncall on same day.
        picked = chosen_by_day.get(day, {})
        return doctor_id in picked.values()

    def _choose_for_slot(day: int, shift_type: ShiftType, avoid_doc_id: int | None = None) -> int | None:
        """
        Choose one doctor_id for this (day, shift_type) using simple priority rules.
        The returned doctor_id MUST be in allowed_slots for that slot.
        """
        allowed_ids = _allowed(day, shift_type)
        if not allowed_ids:
            return None

        # Optionally avoid a specific doctor (e.g., already chosen for onsite that day).
        if avoid_doc_id is not None:
            allowed_ids = [d for d in allowed_ids if d != avoid_doc_id]

        # Priority buckets (most important first).
        # 1) Heads who prefer this concrete day for this shift.
        bucket_1 = [d for d in allowed_ids if _is_head(d) and _prefers_day(d, shift_type, day)]
        chosen = _pick_one(bucket_1)
        if chosen is not None:
            return chosen

        # 2) Heads (even without preferences).
        bucket_2 = [d for d in allowed_ids if _is_head(d)]
        chosen = _pick_one(bucket_2)
        if chosen is not None:
            return chosen

        # 3) Specialists (preferred day first, then any specialist).
        bucket_3a = [d for d in allowed_ids if _is_specialist(d) and _prefers_day(d, shift_type, day)]
        chosen = _pick_one(bucket_3a)
        if chosen is not None:
            return chosen

        bucket_3b = [d for d in allowed_ids if _is_specialist(d)]
        chosen = _pick_one(bucket_3b)
        if chosen is not None:
            return chosen

        # 4) Anyone allowed.
        return _pick_one(allowed_ids)

    # STEP 1: weekends (Sat/Sun) first
    for day in model.days:
        weekday = _weekday(day)
        is_weekend = weekday in (5, 6)
        if not is_weekend:
            continue

        # Seed onsite (max 1 per day)
        if (day, ShiftType.onsite) in model.allowed_slots and (day, ShiftType.onsite) not in model.ignore_slots:
            chosen_onsite = _choose_for_slot(day, ShiftType.onsite)
            if chosen_onsite is not None:
                _set_day_choice(day, ShiftType.onsite, chosen_onsite)

        # Seed oncall (max 1 per day), avoid the onsite doctor if already chosen
        if (day, ShiftType.oncall) in model.allowed_slots and (day, ShiftType.oncall) not in model.ignore_slots:
            avoid_doc = chosen_by_day.get(day, {}).get(ShiftType.onsite.value)
            chosen_oncall = _choose_for_slot(day, ShiftType.oncall, avoid_doc_id=avoid_doc)
            if chosen_oncall is not None and not _already_seeded_same_day(day, chosen_oncall):
                _set_day_choice(day, ShiftType.oncall, chosen_oncall)

    # STEP 2: strong preferred days on weekdays (optional MVP)
    for day in model.days:
        weekday = _weekday(day)
        is_weekend = weekday in (5, 6)
        if is_weekend:
            continue

        # If already seeded for this day, we keep it simple and skip.
        already = chosen_by_day.get(day, {})
        has_onsite_seed = ShiftType.onsite.value in already
        has_oncall_seed = ShiftType.oncall.value in already

        # Prefer heads with strong concrete preferences.
        if (
            not has_onsite_seed
            and (day, ShiftType.onsite) in model.allowed_slots
            and (day, ShiftType.onsite) not in model.ignore_slots
        ):
            allowed_ids = _allowed(day, ShiftType.onsite)
            preferred_heads = [d for d in allowed_ids if _is_head(d) and _prefers_day(d, ShiftType.onsite, day)]
            chosen = _pick_one(preferred_heads)
            if chosen is not None:
                _set_day_choice(day, ShiftType.onsite, chosen)

        if (
            not has_oncall_seed
            and (day, ShiftType.oncall) in model.allowed_slots
            and (day, ShiftType.oncall) not in model.ignore_slots
        ):
            allowed_ids = _allowed(day, ShiftType.oncall)
            preferred_heads = [d for d in allowed_ids if _is_head(d) and _prefers_day(d, ShiftType.oncall, day)]
            chosen = _pick_one(preferred_heads)
            if chosen is not None and not _already_seeded_same_day(day, chosen):
                _set_day_choice(day, ShiftType.oncall, chosen)

    return hints
