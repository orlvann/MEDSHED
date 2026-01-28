# backend/core/engine.py
"""
Adapter for the OR-Tools CP-SAT solver.

This is the ONLY place where we directly import OR-Tools.
Everything else in core works with plain Python structures.
"""

from datetime import datetime
from typing import Dict, List, Tuple

from ortools.sat.python import cp_model

from backend.models.common_enums import DoctorRole, ShiftType

from . import objective_builder, seeding
from .issues import (
    CP_INFEASIBLE,
    FEASIBILITY_ISSUE_MESSAGES,
)
from .types import FeasibilityIssue, HardModel, ProblemData, SolverAssignment, SolverSolution, SolverStatus


def _derive_infeasible_issues(model: HardModel) -> List[FeasibilityIssue]:
    """
    Best-effort, deterministic explanation when CP-SAT returns INFEASIBLE.

    We reuse the same classification logic as feasibility pre-check,
    but we run it on the already-built HardModel.allowed_slots.
    """
    from backend.core.issues import classify_feasibility_issues_for_day

    issues: List[FeasibilityIssue] = []

    def _msg(code: str) -> str:
        return FEASIBILITY_ISSUE_MESSAGES.get(code, code)

    # Build role map once.
    doctor_role_by_id = {int(did): doc.role for did, doc in model.doctors.items() if doc is not None}

    for day in model.active_days:
        onsite_required = (day, ShiftType.onsite) not in model.ignore_slots
        oncall_required = (day, ShiftType.oncall) not in model.ignore_slots

        if not onsite_required and not oncall_required:
            continue

        onsite_ids = set(model.allowed_slots.get((day, ShiftType.onsite), [])) if onsite_required else set()
        oncall_ids = set(model.allowed_slots.get((day, ShiftType.oncall), [])) if oncall_required else set()

        codes = classify_feasibility_issues_for_day(
            onsite_ids=onsite_ids,
            oncall_ids=oncall_ids,
            doctor_role_by_id=doctor_role_by_id,
            onsite_required=onsite_required,
            oncall_required=oncall_required,
        )

        for code in codes:
            issues.append(FeasibilityIssue(day=day, code=code, message=_msg(code)))

    if not issues:
        issues.append(FeasibilityIssue(day=0, code=CP_INFEASIBLE, message=_msg(CP_INFEASIBLE)))

    return issues


def build_and_solve(model: HardModel) -> SolverSolution:
    """
    Build a CP-SAT model for the given HardModel and solve it.

    ```
    Hard constraints enforced:
    - exactly one onsite and one oncall doctor per active day,
    - at least one specialist per active day (in any role),
    - no doctor can be onsite and oncall on the same day,
    - no assignment outside allowed_slots (unavailability + ignore_slots are already "cut out").
    ```
    """
    # If there are no allowed slots at all, the solver has nothing to work with.
    if not model.allowed_slots:
        return SolverSolution(status=SolverStatus.EMPTY, assignments=[])

    # NOTE:
    # Head commitments validation is handled in scheduler.generate_schedule().
    # We intentionally do NOT duplicate it here (avoid double validation).

    # 1) Create CP-SAT model container.
    cp = cp_model.CpModel()

    # 2) Create binary decision variables for each allowed (day, shift_type, doctor) slot.
    #    We do NOT create variables for forbidden combinations.
    x: Dict[Tuple[int, ShiftType, int], cp_model.IntVar] = {}

    for (day, shift_type), doctor_ids in model.allowed_slots.items():
        for doctor_id in doctor_ids:
            x[(day, shift_type, doctor_id)] = cp.NewBoolVar(f"x_d{day}_{shift_type.value}_doc{doctor_id}")

    # 3) Hard constraints -------------------------------------------------------

    # 3.1 Enforce exactly one onsite and one oncall doctor per active day.
    for day in model.active_days:
        # Onsite coverage (only if not ignored)
        if (day, ShiftType.onsite) not in model.ignore_slots:
            onsite_vars = [
                x[(day, ShiftType.onsite, doc_id)]
                for doc_id in model.allowed_slots.get((day, ShiftType.onsite), [])
                if (day, ShiftType.onsite, doc_id) in x
            ]
            if onsite_vars:
                cp.Add(sum(onsite_vars) == 1)
            else:
                cp.Add(0 == 1)  # required slot but no candidates -> infeasible

        # Oncall coverage (only if not ignored)
        if (day, ShiftType.oncall) not in model.ignore_slots:
            oncall_vars = [
                x[(day, ShiftType.oncall, doc_id)]
                for doc_id in model.allowed_slots.get((day, ShiftType.oncall), [])
                if (day, ShiftType.oncall, doc_id) in x
            ]
            if oncall_vars:
                cp.Add(sum(oncall_vars) == 1)
            else:
                cp.Add(0 == 1)  # required slot but no candidates -> infeasible

    # 3.2 Enforce "at least one specialist per day" ONLY when BOTH shifts are required.
    # If admin ignored one shift, we do NOT enforce specialist-per-day (consistent with feasibility + availability).
    for day in model.active_days:
        onsite_required = (day, ShiftType.onsite) not in model.ignore_slots
        oncall_required = (day, ShiftType.oncall) not in model.ignore_slots

        if not onsite_required or not oncall_required:
            # If any shift is not required, skip specialist-per-day rule for this day.
            continue

        specialist_vars: List[cp_model.IntVar] = []

        for shift_type in (ShiftType.onsite, ShiftType.oncall):
            for doc_id in model.allowed_slots.get((day, shift_type), []):
                doctor = model.doctors.get(doc_id)
                if doctor and doctor.role == DoctorRole.specialist:
                    var = x.get((day, shift_type, doc_id))
                    if var is not None:
                        specialist_vars.append(var)

        if specialist_vars:
            cp.Add(sum(specialist_vars) >= 1)
        else:
            cp.Add(0 >= 1)  # both required but no specialist candidate -> infeasible

    # 3.3 Enforce that the same doctor cannot be onsite AND oncall on the same day.
    for day in model.active_days:
        for doc_id in model.participant_doctor_ids:
            v_ons = x.get((day, ShiftType.onsite, doc_id))
            v_onc = x.get((day, ShiftType.oncall, doc_id))
            if v_ons is not None and v_onc is not None:
                cp.Add(v_ons + v_onc <= 1)

    # 4) Objective (soft constraints) ------------------------------------------
    # Build a ProblemData "view" from the HardModel.
    # Rest rules and ETAP 3B objectives need year/month/days + doctors/preferences.
    # ProblemData also requires weekdays, so we compute it here.
    problem_view = ProblemData(
        year=model.year,
        month=model.month,
        days=model.days,
        weekdays={d: datetime(model.year, model.month, d).weekday() for d in model.days},
        doctors=model.doctors,
        preferences=model.preferences,
        participant_doctor_ids=model.participant_doctor_ids,
        ignore_slots=model.ignore_slots,
    )

    # Add rest-rule penalties (ETAP 3A).
    total_rest_penalty = objective_builder.attach_rest_objective(
        cp=cp,
        x=x,
        model=model,
        problem=problem_view,
    )

    # Add preferred concrete days penalties (ETAP 3B).
    total_preferred_days_penalty = objective_builder.attach_preferred_days_objective(
        cp=cp,
        x=x,
        model=model,
        problem=problem_view,
    )

    # Add totals penalties: monthly + weekend max/target (ETAP 3B).
    total_totals_penalty = objective_builder.attach_totals_objective(
        cp=cp,
        x=x,
        model=model,
        problem=problem_view,
    )

    # Add fairness penalties by role groups (ETAP 3C).
    total_fairness_penalty = objective_builder.attach_fairness_objective(
        cp=cp,
        x=x,
        model=model,
        problem=problem_view,
    )

    # Add weekday pattern objective (ETAP 4A).
    total_weekday_patterns_penalty = objective_builder.attach_weekday_patterns_objective(
        cp=cp,
        x=x,
        model=model,
        problem=problem_view,
    )

    # Add preferred partners objective (lower-priority tie-breaker).
    total_preferred_partners_penalty = objective_builder.attach_preferred_partners_objective(
        cp=cp,
        x=x,
        model=model,
        problem=problem_view,
    )

    # Add "avoid Friday if weekend off" objective (very low-priority tie-breaker).
    total_friday_free_weekend_penalty = objective_builder.attach_avoid_friday_if_weekend_off_objective(
        cp=cp,
        x=x,
        model=model,
        problem=problem_view,
    )

    # Combined objective:
    # - rest rules have strong weights (from scoring.py),
    # - preferred days and totals are additional soft goals,
    # - fairness tries to balance load inside role groups,
    # - weekday patterns are a lower-priority tie-breaker.
    cp.Minimize(
        total_rest_penalty
        + total_preferred_days_penalty
        + total_totals_penalty
        + total_fairness_penalty
        + total_weekday_patterns_penalty
        + total_preferred_partners_penalty
        + total_friday_free_weekend_penalty
    )

    # 5) Solve -----------------------------------------------------------------
    solver = cp_model.CpSolver()

    # Provide a warm-start hint to the solver.
    # This does NOT enforce assignments; the solver may override them
    # if needed to satisfy constraints or improve the objective.
    seed_hints = seeding.generate_initial_hints(model=model, problem=problem_view)

    for (day, doctor_id, shift_type), val in seed_hints.items():
        # Our x key order is (day, shift_type, doctor_id)
        var = x.get((day, shift_type, doctor_id))
        if var is None:
            # Defensive: skip hints for non-existing/forbidden slots.
            continue

        # AddHint attaches a suggestion to the CP model (not a hard rule).
        cp.AddHint(var, int(val))

    status = solver.Solve(cp)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        status_enum = SolverStatus.OK
    elif status == cp_model.INFEASIBLE:
        status_enum = SolverStatus.INFEASIBLE
    else:
        # For example: UNKNOWN, MODEL_INVALID, etc.
        status_enum = SolverStatus.NOT_SOLVED

    if status_enum is not SolverStatus.OK:
        # If CP-SAT is infeasible, try to provide a user-friendly explanation.
        if status_enum == SolverStatus.INFEASIBLE:
            issues = _derive_infeasible_issues(model)
            return SolverSolution(status=status_enum, assignments=[], issues=issues)

        return SolverSolution(status=status_enum, assignments=[])

    # 6) Build SolverAssignment list from chosen Boolean variables.
    assignments: List[SolverAssignment] = []

    for (day, shift_type, doc_id), var in x.items():
        if solver.BooleanValue(var):
            assignments.append(
                SolverAssignment(
                    day=day,
                    shift_type=shift_type,
                    doctor_id=doc_id,
                )
            )

    # Deterministic ordering (helps tests and stable API payloads).
    assignments.sort(key=lambda a: (a.day, a.shift_type.value, a.doctor_id))

    return SolverSolution(status=SolverStatus.OK, assignments=assignments)
