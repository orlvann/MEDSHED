# backend/core/seeding.py
"""
Warm-start / seeding logic for the solver.

This module produces "hints" for the solver:
- suggested assignments for heads on their preferred days ("head commitments"),
- initial coverage for hardest slots (few available doctors).

IMPORTANT:
- Hints are NOT constraints. The solver may ignore them if needed.
- Head commitments are validated separately (must-have input rules).
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Tuple

from backend.models.common_enums import DoctorRole, ShiftType

from .issues import (
    FEASIBILITY_ISSUE_MESSAGES,
    HEAD_COMMITMENT_CONFLICT,
    HEAD_COMMITMENT_DOUBLE_SHIFT_SAME_DAY,
    HEAD_COMMITMENT_IGNORED_SLOT,
    HEAD_COMMITMENT_NOT_ALLOWED,
)
from .types import FeasibilityIssue, HardModel, ProblemData

SeedHintKey = Tuple[int, int, ShiftType]  # (day, doctor_id, shift_type)


def validate_head_commitments(model: HardModel) -> List[FeasibilityIssue]:
    """
    Validate "Head commitments" (must-have head preferred slots) using HardModel.allowed_slots.

    Rules (confirmed):
    - ignore_days is NOT used anymore.
    - If a head prefers a slot that is ignored (in ignore_slots) -> issue
    - If a head is not allowed for the preferred slot -> issue
    - If multiple heads prefer the same slot -> issue
    - If the same head prefers onsite and oncall on the same day -> issue

    Returns:
        List[FeasibilityIssue] (empty list means "OK").
    """
    issues: List[FeasibilityIssue] = []

    def _add_issue(day: int, code: str, extra: str | None = None) -> None:
        """Create a FeasibilityIssue with a stable default message."""
        base = FEASIBILITY_ISSUE_MESSAGES.get(code, code)
        msg = base if not extra else f"{base} {extra}"
        issues.append(FeasibilityIssue(day=day, code=code, message=msg))

    # Deterministic ordering for stable output.
    head_ids = sorted([doc_id for doc_id, doc in model.doctors.items() if doc.is_head])

    # Track (day, shift_type) -> head_id to detect head-head conflicts.
    seen_slot_owner: Dict[Tuple[int, ShiftType], int] = {}

    for head_id in head_ids:
        pref = model.preferences.get(head_id)
        if pref is None:
            continue

        # Same head wants onsite and oncall on the same day -> issue.
        both_days = set(pref.preferred_onsite_days).intersection(set(pref.preferred_oncall_days))
        for d in sorted(both_days):
            _add_issue(d, HEAD_COMMITMENT_DOUBLE_SHIFT_SAME_DAY, extra=f"(head_id={head_id})")

        # ---- Onsite commitments ---------------------------------------------
        for d in sorted(pref.preferred_onsite_days):
            if (d, ShiftType.onsite) in model.ignore_slots:
                _add_issue(d, HEAD_COMMITMENT_IGNORED_SLOT, extra=f"(head_id={head_id}, shift=onsite)")
                continue

            allowed = model.allowed_slots.get((d, ShiftType.onsite))
            if not allowed or head_id not in allowed:
                _add_issue(d, HEAD_COMMITMENT_NOT_ALLOWED, extra=f"(head_id={head_id}, shift=onsite)")
                continue

            slot_key = (d, ShiftType.onsite)
            other = seen_slot_owner.get(slot_key)
            if other is not None and other != head_id:
                _add_issue(
                    d,
                    HEAD_COMMITMENT_CONFLICT,
                    extra=f"(shift=onsite, head_id={head_id}, other_head_id={other})",
                )
            else:
                seen_slot_owner[slot_key] = head_id

        # ---- Oncall commitments ---------------------------------------------
        for d in sorted(pref.preferred_oncall_days):
            if (d, ShiftType.oncall) in model.ignore_slots:
                _add_issue(d, HEAD_COMMITMENT_IGNORED_SLOT, extra=f"(head_id={head_id}, shift=oncall)")
                continue

            allowed = model.allowed_slots.get((d, ShiftType.oncall))
            if not allowed or head_id not in allowed:
                _add_issue(d, HEAD_COMMITMENT_NOT_ALLOWED, extra=f"(head_id={head_id}, shift=oncall)")
                continue

            slot_key = (d, ShiftType.oncall)
            other = seen_slot_owner.get(slot_key)
            if other is not None and other != head_id:
                _add_issue(
                    d,
                    HEAD_COMMITMENT_CONFLICT,
                    extra=f"(shift=oncall, head_id={head_id}, other_head_id={other})",
                )
            else:
                seen_slot_owner[slot_key] = head_id

    return issues


def generate_initial_hints(model: HardModel, problem: ProblemData) -> Dict[SeedHintKey, int]:
    """
    Build a warm-start (seeding) hint map for the CP-SAT solver.

    Confirmed behavior:
    1) Seed ALL "Head commitments" first:
       - head preferred onsite/oncall days are suggested before anything else.
    2) Then seed TOP K hardest slots (weekends + hard weekdays):
       - difficulty = number of allowed candidates for the slot,
       - sort by (difficulty asc, day asc, shift_type asc),
       - K = min(10, number_of_slots).
    3) Deterministic picks:
       - preferred candidates first (smallest doctor_id),
       - otherwise any allowed (smallest doctor_id),
       - never hint the same doctor for onsite+oncall on the same day.
    4) Bonus (soft, only for realism of the start):
       - if a day has no hinted specialist yet, prefer a specialist for the next seeded slot
         (when available).

    Notes:
    - Seeding does not create constraints.
    - We only add "1" hints (we do not add zeros).
    """
    hints: Dict[SeedHintKey, int] = {}

    # Track which doctor_ids are already hinted for a given day,
    # so we do not hint onsite+oncall for the same doctor on the same day.
    chosen_doctors_by_day: Dict[int, set[int]] = {}

    # Track which slots already have a hint (slot = day + shift).
    seeded_slots: set[Tuple[int, ShiftType]] = set()

    active_days_set = set(model.active_days)

    def _weekday(day: int) -> int:
        """Return weekday number: 0=Mon .. 6=Sun (pure date, no timezone logic)."""
        return datetime(model.year, model.month, day).weekday()

    def _allowed(day: int, shift_type: ShiftType) -> List[int]:
        """Return allowed doctor ids for the slot. If slot missing -> empty."""
        return list(model.allowed_slots.get((day, shift_type), []))

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

    def _day_has_specialist_hint(day: int) -> bool:
        """Check if we already hinted any specialist on this day (onsite or oncall)."""
        for doc_id in chosen_doctors_by_day.get(day, set()):
            if _is_specialist(doc_id):
                return True
        return False

    def _pick_smallest(ids: List[int]) -> int | None:
        """Deterministic pick: smallest doctor_id."""
        if not ids:
            return None
        return sorted(ids)[0]

    def _can_use_doctor_for_day(day: int, doctor_id: int) -> bool:
        """Avoid hinting the same doctor for two shifts in the same day."""
        return doctor_id not in chosen_doctors_by_day.get(day, set())

    def _add_hint(day: int, shift_type: ShiftType, doctor_id: int) -> None:
        """Store a hint '1' for a slot and remember it for 'no double shift' rule."""
        hints[(day, doctor_id, shift_type)] = 1
        chosen_doctors_by_day.setdefault(day, set()).add(doctor_id)
        seeded_slots.add((day, shift_type))

    def _choose_candidate(day: int, shift_type: ShiftType) -> int | None:
        """
        Choose a candidate for a given slot following the confirmed rules.
        Returns doctor_id or None if no candidate can be chosen.
        """
        allowed_ids = _allowed(day, shift_type)
        if not allowed_ids:
            return None

        # Remove doctors already hinted on the other slot of the same day.
        allowed_ids = [d for d in allowed_ids if _can_use_doctor_for_day(day, d)]
        if not allowed_ids:
            return None

        day_needs_specialist = not _day_has_specialist_hint(day)

        # Preferred candidates for this slot.
        preferred_ids = [d for d in allowed_ids if _prefers_day(d, shift_type, day)]

        # Bonus: if day has no specialist hinted yet, prefer a specialist within preferred.
        if day_needs_specialist:
            pref_spec = [d for d in preferred_ids if _is_specialist(d)]
            chosen = _pick_smallest(pref_spec)
            if chosen is not None:
                return chosen

        # Normal preferred pick.
        chosen = _pick_smallest(preferred_ids)
        if chosen is not None:
            return chosen

        # Fallback: any allowed, but still try specialist first if day needs it.
        if day_needs_specialist:
            any_spec = [d for d in allowed_ids if _is_specialist(d)]
            chosen = _pick_smallest(any_spec)
            if chosen is not None:
                return chosen

        return _pick_smallest(allowed_ids)

    # -------------------------------------------------------------------------
    # STEP 1: Seed all head commitments first (must-have head preferred slots).
    # NOTE: Validation is performed outside (scheduler/engine). Here we only seed.
    # -------------------------------------------------------------------------
    head_ids = sorted([doc_id for doc_id, doc in model.doctors.items() if doc.is_head])

    for head_id in head_ids:
        pref = model.preferences.get(head_id)
        if pref is None:
            continue

        # Onsite commitments first (stable).
        for day in sorted(pref.preferred_onsite_days):
            if day not in active_days_set:
                continue
            if (day, ShiftType.onsite) in model.ignore_slots:
                continue
            if head_id not in _allowed(day, ShiftType.onsite):
                continue
            if not _can_use_doctor_for_day(day, head_id):
                continue
            _add_hint(day, ShiftType.onsite, head_id)

        # Oncall commitments next.
        for day in sorted(pref.preferred_oncall_days):
            if day not in active_days_set:
                continue
            if (day, ShiftType.oncall) in model.ignore_slots:
                continue
            if head_id not in _allowed(day, ShiftType.oncall):
                continue
            if not _can_use_doctor_for_day(day, head_id):
                continue
            _add_hint(day, ShiftType.oncall, head_id)

    # -------------------------------------------------------------------------
    # STEP 2: Seed TOP K hardest slots (weekends + hard weekdays) by difficulty.
    # We don't need to explicitly filter weekends here, because "difficulty"
    # naturally surfaces "hard" weekends and "hard" weekdays (e.g., holidays).
    # -------------------------------------------------------------------------
    candidate_slots: List[Tuple[int, ShiftType, int]] = []

    for day in sorted(active_days_set):
        for shift_type in (ShiftType.onsite, ShiftType.oncall):
            if (day, shift_type) in model.ignore_slots:
                continue
            if (day, shift_type) not in model.allowed_slots:
                continue

            # Skip slots already seeded (usually by head commitments).
            if (day, shift_type) in seeded_slots:
                continue

            difficulty = len(_allowed(day, shift_type))
            candidate_slots.append((day, shift_type, int(difficulty)))

    # Sort by: hardest first (fewest candidates), then day, then shift_type.
    candidate_slots.sort(key=lambda t: (t[2], t[0], t[1].value))

    k = min(10, len(candidate_slots))

    for day, shift_type, _diff in candidate_slots[:k]:
        chosen = _choose_candidate(day, shift_type)
        if chosen is None:
            continue
        _add_hint(day, shift_type, chosen)

    return hints
