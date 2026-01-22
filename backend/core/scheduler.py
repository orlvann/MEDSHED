# backend/core/scheduler.py
"""
High-level orchestration of the scheduling process.

This module:
- takes ProblemData (built by services),
- optionally applies seeding / preprocessing,
- builds the constraint model,
- calls the OR-Tools engine to solve it,
- optionally applies heuristics,
- converts the solution to a list of Assignment DTOs.
"""
from dataclasses import dataclass
from typing import List

from backend.models.schemas.schedule import Assignment

from . import (
    constraint_builder,
    engine,
    seeding,
)
from .feasibility import analyze_problem
from .types import HardModel, ProblemData, SolverAssignment, SolverSolution, SolverStatus


@dataclass
class ScheduleResult:
    """
    Bundle of raw solver solution and finalized Assignment DTOs.
    """

    solution: SolverSolution
    assignments: List[Assignment]


def generate_schedule(problem: ProblemData) -> ScheduleResult:
    """
    High-level entry point for schedule generation.

    Input:
    - ProblemData (already built by services from DB data).

    Output:
    - List[Assignment] (API-level DTOs returned to services).

    Steps:
    1) Seeding (warm-start) is implemented in backend/core/seeding.py,
    but it is applied inside engine.build_and_solve via CP-SAT hints.
    (Hints need CP variables x[...] to exist.)
    2) Build a HardModel (allowed_slots + structural data).
    allowed_slots already respect:
    - ignore_days / ignore_slots,
    - unavailable_*_days from preferences.
    3) Solve using the CP-SAT engine (hard constraints + soft objectives).
    4) (Later) optional heuristic polishing.
    5) Map SolverSolution -> Assignment via _solution_to_assignments.
    """

    # 0) Feasibility pre-check (cheap, deterministic)
    issues = analyze_problem(problem)
    if issues:
        solution = SolverSolution(
            status=SolverStatus.INFEASIBLE,
            assignments=[],
            issues=issues,
        )
        return ScheduleResult(solution=solution, assignments=[])

    # 1) Seeding (warm-start) is implemented in: backend/core/seeding.py
    #    It is applied inside engine.build_and_solve (via CP-SAT hints),
    #    because hints need CP variables to exist (x[...] is built there).

    # 2) Build the hard-constraint model (no OR-Tools calls here).
    #    This step defines the decision variables and all "must-have" rules:
    #    - exactly 1 onsite and 1 oncall per day,
    #    - at least one specialist per day,
    #    - no double-role for the same doctor on the same day,
    #    - no assignments on unavailable days,
    #    - respect ignore_days / ignore_slots.
    hard_model: HardModel = constraint_builder.build_hard_model(problem)

    # 2.1) Validate "Head commitments" (must-have head preferred slots).
    # We validate here (before OR-Tools) because HardModel.allowed_slots is needed.
    commitment_issues = seeding.validate_head_commitments(hard_model)
    if commitment_issues:
        solution = SolverSolution(
            status=SolverStatus.INFEASIBLE,
            assignments=[],
            issues=commitment_issues,
        )
        return ScheduleResult(solution=solution, assignments=[])

    # 3) Soft objectives are handled inside engine.build_and_solve (objective_builder).
    # The engine applies:
    # - rest rules between shifts,
    # - preferred concrete days,
    # - max/target totals and weekend loads,
    # - fairness inside role groups,
    # - weekday patterns, partner preferences, and other tie-breakers.
    model_for_solver = hard_model

    # 4) Solve using OR-Tools CP-SAT (engine is the only place that imports OR-Tools)
    solution: SolverSolution = engine.build_and_solve(model_for_solver)

    # 5) Heuristics polishing will be added later (keep the pipeline simple for now).
    #    For MVP this returns the original solution.
    final_solution = solution

    # 6) Convert the final solution into API-level Assignment DTOs.
    assignments = _solution_to_assignments(final_solution, problem)
    return ScheduleResult(solution=final_solution, assignments=assignments)


def _solution_to_assignments(solution: SolverSolution, problem: ProblemData) -> List[Assignment]:
    """
    Convert the low-level solver solution into a list of Assignment DTOs.

    This helper keeps the mapping logic in one place, so that:
    - services see only clean Assignment objects,
    - engine/constraint_builder can work with more technical structures.

    For MVP:
    - if solver status is not OK, we return an empty list,
    - otherwise we map each SolverAssignment to Assignment and sort the result.
    """
    # Early exit: for non-OK statuses we do not expose any assignments in MVP.
    if solution.status is not SolverStatus.OK:
        # Later we may decide to surface partial results or diagnostics here.
        return []

    # Local list for DTO assignments returned to services / API layer.
    assignments: List[Assignment] = []

    # Explicitly type the internal solver assignments (helps readers and tools).
    solver_assignments: List[SolverAssignment] = solution.assignments

    for sa in solver_assignments:
        # Simple dataclass -> DTO mapping.
        assignments.append(
            Assignment(
                day=sa.day,
                shift_type=sa.shift_type,
                doctor_id=sa.doctor_id,
            )
        )

    # Ensure deterministic ordering of API payloads.
    # We sort by (day, shift_type value, doctor_id).
    assignments.sort(key=lambda a: (a.day, a.shift_type.value, a.doctor_id))

    # `problem` is kept in the signature for future extensions
    # (e.g. mapping extra metadata); it is not used in MVP.
    return assignments
