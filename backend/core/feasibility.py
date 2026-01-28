# backend/core/feasibility.py
"""
Quick feasibility checks for the solver.

This module performs lightweight, deterministic checks on ProblemData
*before* building the CP-SAT model. Its purpose is to detect obvious
impossibilities early and provide clear diagnostics to the caller.

No SQLAlchemy, no FastAPI, no OR-Tools — pure core logic only.

POLICY (must match constraint_builder.py):
- ignore_days: whole day is removed from solver scope (no slots required).
- ignore_slots: individual (day, shift_type) slots removed from scope (not required).
- If BOTH shifts are ignored for a day (via ignore_slots), day is effectively skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set

from backend.core.issues import FEASIBILITY_ISSUE_MESSAGES, classify_feasibility_issues_for_day
from backend.core.types import FeasibilityIssue, ProblemData
from backend.models.common_enums import DoctorRole, ShiftType


@dataclass
class DayCapacity:
    """
    Capacity summary for a single day.

    We count how many doctors of each role can work each shift
    (taking ignore_days + ignore_slots + unavailable days into account).

    IMPORTANT:
    - We also keep candidate ID sets for onsite and oncall.
      This allows detecting the real "forced double shift" case:
      the same single doctor is the only candidate for BOTH shifts.
    """

    day: int

    # Counts by role and shift (useful for UI summaries / debugging).
    spec_onsite: int = 0
    res_onsite: int = 0
    spec_oncall: int = 0
    res_oncall: int = 0

    # Identity-aware candidate sets (needed for precise issue classification).
    onsite_ids: Set[int] = field(default_factory=set)
    oncall_ids: Set[int] = field(default_factory=set)


def compute_day_capacity(problem: ProblemData) -> Dict[int, DayCapacity]:
    """
    Build capacity summary for each day that is in solver scope.

    Rules:
    - If day is in ignore_days -> day is skipped entirely.
    - If BOTH shifts are ignored via ignore_slots -> day is skipped entirely.
    - For remaining days, build candidate sets/counts only for REQUIRED slots.
    """
    capacity: Dict[int, DayCapacity] = {}

    for day in problem.days:
        day = int(day)

        # Whole day ignored -> solver does not schedule it -> no feasibility checks needed.
        if day in (problem.ignore_days or set()):
            continue

        # If both shifts are ignored, solver does not schedule this day at all.
        both_ignored = (day, ShiftType.onsite) in problem.ignore_slots and (
            day,
            ShiftType.oncall,
        ) in problem.ignore_slots
        if both_ignored:
            continue

        cap = DayCapacity(day=day)

        for doctor_id in problem.participant_doctor_ids:
            doctor_id = int(doctor_id)
            doctor = problem.doctors.get(doctor_id)
            prefs = problem.preferences.get(doctor_id)

            # Defensive: missing data -> ignore this doctor for pre-checks
            if doctor is None or prefs is None:
                continue

            # ---- Onsite (only if this slot is REQUIRED) ---------------------
            if (day, ShiftType.onsite) not in problem.ignore_slots:
                if day not in (prefs.unavailable_onsite_days or []):
                    cap.onsite_ids.add(doctor_id)
                    if doctor.role == DoctorRole.specialist:
                        cap.spec_onsite += 1
                    else:
                        cap.res_onsite += 1

            # ---- Oncall (only if this slot is REQUIRED) ---------------------
            if (day, ShiftType.oncall) not in problem.ignore_slots:
                if day not in (prefs.unavailable_oncall_days or []):
                    cap.oncall_ids.add(doctor_id)
                    if doctor.role == DoctorRole.specialist:
                        cap.spec_oncall += 1
                    else:
                        cap.res_oncall += 1

        capacity[day] = cap

    return capacity


def analyze_problem(problem: ProblemData) -> List[FeasibilityIssue]:
    """
    Run quick feasibility checks before building the CP-SAT model.

    Rules:
    - ignore_days: whole day is not checked (not required at all).
    - ignore_slots: ignored slot is not required and is not checked.
    """
    issues: List[FeasibilityIssue] = []

    capacity_by_day = compute_day_capacity(problem)

    # Build role map once (single source of truth for "is specialist").
    doctor_role_by_id = {int(did): doc.role for did, doc in problem.doctors.items() if doc is not None}

    def _add_issue(day: int, code: str) -> None:
        """Append a FeasibilityIssue with a stable default message."""
        issues.append(
            FeasibilityIssue(
                day=int(day),
                code=str(code),
                message=FEASIBILITY_ISSUE_MESSAGES.get(str(code), str(code)),
            )
        )

    for day, cap in capacity_by_day.items():
        day = int(day)

        onsite_required = (day, ShiftType.onsite) not in problem.ignore_slots
        oncall_required = (day, ShiftType.oncall) not in problem.ignore_slots

        # If neither shift is required, nothing to check.
        if not onsite_required and not oncall_required:
            continue

        # IMPORTANT:
        # Pass empty sets for non-required shifts, so the classifier is consistent.
        onsite_ids = set(cap.onsite_ids) if onsite_required else set()
        oncall_ids = set(cap.oncall_ids) if oncall_required else set()

        codes = classify_feasibility_issues_for_day(
            onsite_ids=onsite_ids,
            oncall_ids=oncall_ids,
            doctor_role_by_id=doctor_role_by_id,
            onsite_required=onsite_required,
            oncall_required=oncall_required,
        )

        for code in codes:
            _add_issue(day, code)

    return issues
