# backend/core/feasibility.py
"""
Quick feasibility checks for the solver.

This module performs lightweight, deterministic checks on ProblemData
*before* building the CP-SAT model. Its purpose is to detect obvious
impossibilities early and provide clear diagnostics to the caller.

No SQLAlchemy, no FastAPI, no OR-Tools — pure core logic only.
"""

from dataclasses import dataclass
from typing import Dict, List

from backend.core.issues import (
    FEASIBILITY_ISSUE_MESSAGES,
    NO_ONCALL_CANDIDATE,
    NO_ONSITE_CANDIDATE,
    NO_SPECIALIST,
    SINGLE_CANDIDATE_FOR_BOTH_ROLES,
)
from backend.core.types import FeasibilityIssue, ProblemData
from backend.models.common_enums import DoctorRole, ShiftType


@dataclass
class DayCapacity:
    """
    Capacity summary for a single day.

    We count how many doctors of each role can work each shift
    (taking ignore_slots and unavailable days into account).
    """

    day: int
    spec_onsite: int = 0
    res_onsite: int = 0
    spec_oncall: int = 0
    res_oncall: int = 0


def compute_day_capacity(problem: ProblemData) -> Dict[int, DayCapacity]:
    """
    Build capacity summary for each day (excluding ignore_days / ignore_slots).

    For each day we count how many specialists / residents are candidates for:
    - onsite
    - oncall

    Respecting:
    - participant_doctor_ids,
    - unavailable_*_days from preferences,
    - ignore_days,
    - ignore_slots.

    IMPORTANT:
    - If a slot is ignored, we do NOT count candidates for it.
      (Because the solver will not schedule this slot at all.)
    """
    capacity: Dict[int, DayCapacity] = {}

    for day in problem.days:
        # Skip fully ignored days
        if day in problem.ignore_days:
            continue

        # If both shifts are ignored, day is effectively empty -> skip
        if (day, ShiftType.onsite) in problem.ignore_slots and (day, ShiftType.oncall) in problem.ignore_slots:
            continue

        cap = DayCapacity(day=day)

        for doctor_id in problem.participant_doctor_ids:
            doctor = problem.doctors.get(doctor_id)
            prefs = problem.preferences.get(doctor_id)

            # Defensive: missing data -> ignore this doctor for pre-checks
            if doctor is None or prefs is None:
                continue

            # ---- Onsite -----------------------------------------------------
            # Count only if the slot is REQUIRED (not ignored)
            if (day, ShiftType.onsite) not in problem.ignore_slots:
                if day not in prefs.unavailable_onsite_days:
                    if doctor.role == DoctorRole.specialist:
                        cap.spec_onsite += 1
                    else:
                        cap.res_onsite += 1

            # ---- Oncall -----------------------------------------------------
            # Count only if the slot is REQUIRED (not ignored)
            if (day, ShiftType.oncall) not in problem.ignore_slots:
                if day not in prefs.unavailable_oncall_days:
                    if doctor.role == DoctorRole.specialist:
                        cap.spec_oncall += 1
                    else:
                        cap.res_oncall += 1

        capacity[day] = cap

    return capacity


def analyze_problem(problem: ProblemData) -> List[FeasibilityIssue]:
    """
    Run quick feasibility checks before building the CP-SAT model.

    IMPORTANT GUARANTEE:
    - We must respect ignore_slots.
      If a slot is ignored, it is NOT required, so we must NOT emit "no_*_candidate"
      for that slot.

    Rules (per day, only for REQUIRED shifts):
    - if onsite is required and has 0 candidates -> "no_onsite_candidate"
    - if oncall is required and has 0 candidates -> "no_oncall_candidate"
    - if at least one shift is required and there is 0 specialists among REQUIRED shifts -> "no_specialist"
    - if BOTH shifts are required and total candidates across both shifts == 1 -> "single_candidate_for_both_roles"
    """
    issues: List[FeasibilityIssue] = []

    capacity_by_day = compute_day_capacity(problem)

    def _add_issue(day: int, code: str) -> None:
        """Append a FeasibilityIssue with a stable default message."""
        issues.append(
            FeasibilityIssue(
                day=day,
                code=code,
                message=FEASIBILITY_ISSUE_MESSAGES.get(code, code),
            )
        )

    for day, cap in capacity_by_day.items():
        onsite_required = (day, ShiftType.onsite) not in problem.ignore_slots
        oncall_required = (day, ShiftType.oncall) not in problem.ignore_slots

        # Defensive: if neither shift is required, day should not appear here,
        # but keep it safe anyway.
        if not onsite_required and not oncall_required:
            continue

        total_onsite = cap.spec_onsite + cap.res_onsite
        total_oncall = cap.spec_oncall + cap.res_oncall

        # Missing candidates only matter for REQUIRED shifts.
        if onsite_required and total_onsite == 0:
            _add_issue(day, NO_ONSITE_CANDIDATE)

        if oncall_required and total_oncall == 0:
            _add_issue(day, NO_ONCALL_CANDIDATE)

        # Specialist requirement is defined only across REQUIRED shifts.
        total_specialists_required = 0
        if onsite_required:
            total_specialists_required += cap.spec_onsite
        if oncall_required:
            total_specialists_required += cap.spec_oncall

        if total_specialists_required == 0:
            _add_issue(day, NO_SPECIALIST)

        # "Roles cannot be split" only makes sense when BOTH shifts are required.
        if onsite_required and oncall_required:
            total_candidates = total_onsite + total_oncall
            if total_candidates == 1:
                _add_issue(day, SINGLE_CANDIDATE_FOR_BOTH_ROLES)

    return issues
