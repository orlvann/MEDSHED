# backend/core/feasibility.py
"""
Quick feasibility checks for the solver.

This module performs lightweight, deterministic checks on ProblemData
*before* building the CP-SAT model. Its purpose is to detect obvious
impossibilities early and provide clear diagnostics to the caller.

No SQLAlchemy, no FastAPI, no OR-Tools — pure core logic only.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set

from backend.core.issues import (
    FEASIBILITY_ISSUE_MESSAGES,
    classify_feasibility_issues_for_day,
)
from backend.core.types import FeasibilityIssue, ProblemData
from backend.models.common_enums import DoctorRole, ShiftType


@dataclass
class DayCapacity:
    """
    Capacity summary for a single day.

    We count how many doctors of each role can work each shift
    (taking ignore_slots and unavailable days into account).

    IMPORTANT:
    - We also keep candidate ID sets for onsite and oncall.
      This allows detecting the real "forced double shift" case:
      the same single doctor is the only candidate for both shifts.
    """

    day: int
    spec_onsite: int = 0
    res_onsite: int = 0
    spec_oncall: int = 0
    res_oncall: int = 0

    onsite_ids: Set[int] = field(default_factory=set)
    oncall_ids: Set[int] = field(default_factory=set)


def compute_day_capacity(problem: ProblemData) -> Dict[int, DayCapacity]:
    """
    Build capacity summary for each day (excluding ignore_days / ignore_slots).

    IMPORTANT:
    - If a slot is ignored, we do NOT count candidates for it
      (because the solver will not schedule this slot at all).
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
            if (day, ShiftType.onsite) not in problem.ignore_slots:
                if day not in prefs.unavailable_onsite_days:
                    cap.onsite_ids.add(int(doctor_id))
                    if doctor.role == DoctorRole.specialist:
                        cap.spec_onsite += 1
                    else:
                        cap.res_onsite += 1

            # ---- Oncall -----------------------------------------------------
            if (day, ShiftType.oncall) not in problem.ignore_slots:
                if day not in prefs.unavailable_oncall_days:
                    cap.oncall_ids.add(int(doctor_id))
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

    This function is now tiny because the classification logic lives in core/issues.py.
    """
    issues: List[FeasibilityIssue] = []

    capacity_by_day = compute_day_capacity(problem)

    # Build role map once (single source of truth for "is specialist").
    doctor_role_by_id = {int(did): doc.role for did, doc in problem.doctors.items() if doc is not None}

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

        # If neither shift is required, nothing to check.
        if not onsite_required and not oncall_required:
            continue

        onsite_ids = cap.onsite_ids if onsite_required else set()
        oncall_ids = cap.oncall_ids if oncall_required else set()

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
