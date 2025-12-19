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
    classify_feasibility_issues_for_counts,
)
from backend.core.types import FeasibilityIssue, ProblemData
from backend.models.common_enums import DoctorRole, ShiftType


@dataclass
class DayCapacity:
    """
    Capacity summary for a single day.

    ```
    Counts how many doctors of each role can work each shift.
    """

    day: int
    spec_onsite: int = 0
    res_onsite: int = 0
    spec_oncall: int = 0
    res_oncall: int = 0


def compute_day_capacity(problem: ProblemData) -> Dict[int, DayCapacity]:
    """
    Build capacity summary for each day (excluding ignore_days / ignore_slots).

    ```
    For each day we count how many specialists / residents are candidates for:
    - onsite
    - oncall

    Respecting:
    - participant_doctor_ids,
    - unavailable_*_days from preferences,
    - ignore_days,
    - ignore_slots.
    """
    capacity: Dict[int, DayCapacity] = {}

    for day in problem.days:
        # Skip fully ignored days
        if day in problem.ignore_days:
            continue

        cap = DayCapacity(day=day)

        for doctor_id in problem.participant_doctor_ids:
            doctor = problem.doctors.get(doctor_id)
            prefs = problem.preferences.get(doctor_id)

            if doctor is None or prefs is None:
                continue

            # ---- Onsite -----------------------------------------------------
            if (day, ShiftType.onsite) not in problem.ignore_slots:
                if day not in prefs.unavailable_onsite_days:
                    if doctor.role == DoctorRole.specialist:
                        cap.spec_onsite += 1
                    else:
                        cap.res_onsite += 1

            # ---- Oncall -----------------------------------------------------
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

    ```
    Rules (per non-ignored day) are defined in backend.core.issues:
    - no onsite candidates        -> "no_onsite_candidate"
    - no oncall candidates        -> "no_oncall_candidate"
    - no specialist at all        -> "no_specialist"
    - only one total candidate    -> "single_candidate_for_both_roles"
    """
    issues: List[FeasibilityIssue] = []

    capacity_by_day = compute_day_capacity(problem)

    for day, cap in capacity_by_day.items():
        total_onsite = cap.spec_onsite + cap.res_onsite
        total_oncall = cap.spec_oncall + cap.res_oncall
        total_specialists = cap.spec_onsite + cap.spec_oncall

        codes = classify_feasibility_issues_for_counts(
            total_onsite=total_onsite,
            total_oncall=total_oncall,
            total_specialists=total_specialists,
        )

        for code in codes:
            message = FEASIBILITY_ISSUE_MESSAGES.get(code, code)
            issues.append(
                FeasibilityIssue(
                    day=day,
                    code=code,
                    message=message,
                )
            )

    return issues
