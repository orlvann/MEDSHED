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

from typing import List

from backend.models.schemas.schedule import Assignment

from . import (
    constraint_builder,
    engine,
    seeding,
)
from .types import HardModel, ProblemData, SolverAssignment, SolverSolution, SolverStatus


def generate_schedule(problem: ProblemData) -> List[Assignment]:
    """
    High-level entry point for schedule generation.

    Input:
    - ProblemData (already built by services from DB data).

    Output:
    - List[Assignment] (API-level DTOs returned to services).

    Steps:
    1) Build optional warm-start hints (seeding).
    MVP: hints are just a placeholder (can be empty).
    2) Build a HardModel (allowed_slots + structural data).
    allowed_slots already respect:
    - ignore_days / ignore_slots,
    - unavailable_*_days from preferences.
    3) (Later) attach soft constraints / objective weights.
    MVP: we skip objectives and solve only hard constraints.
    4) Call the CP-SAT engine to get a SolverSolution.
    5) (Later) optional heuristic polishing.
    6) Map SolverSolution -> Assignment via _solution_to_assignments.
    """

    # 1) Warm-start hints (MVP: placeholder).
    #    Example hints:
    #    - heads (is_head=True) on their preferred days,
    #    - hardest slots (few available doctors),
    #    - weekend onsite+oncall combos for doctors who allow it.
    seed_hints = seeding.generate_initial_hints(problem)

    # 2) Build the hard-constraint model (no OR-Tools calls here).
    #    This step defines the decision variables and all "must-have" rules:
    #    - exactly 1 onsite and 1 oncall per day,
    #    - at least one specialist per day,
    #    - no double-role for the same doctor on the same day,
    #    - no assignments on unavailable days,
    #    - respect ignore_days / ignore_slots.
    hard_model: HardModel = constraint_builder.build_hard_model(problem, seed_hints)

    # 3) Soft constraints/objectives will be implemented here in later stages.
    #    For this stage we solve ONLY the hard model.
    #    Here we will use preferences and fairness:
    #    - strong preferences for heads > specialists > residents,
    #    - rest rules between shifts,
    #    - max/target totals and weekend loads,
    #    - weekday patterns, partner preferences, etc.
    model_for_solver = hard_model

    # 4) Solve using OR-Tools CP-SAT (engine is the only place that imports OR-Tools)
    solution: SolverSolution = engine.build_and_solve(model_for_solver)

    # 5) Heuristics polishing will be added later (keep the pipeline simple for now).
    #    For MVP this returns the original solution.
    final_solution = solution

    # 6) Convert the final solution into API-level Assignment DTOs.
    return _solution_to_assignments(final_solution, problem)


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
