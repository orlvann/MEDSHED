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
    heuristics,  # will be used later
    objective_builder,
    seeding,
)
from .types import ProblemData


def generate_schedule(problem: ProblemData) -> List[Assignment]:
    """
    Entry point for the solver core.

    Services are responsible for:
    - loading doctors, preferences, and schedule settings from the DB,
    - filtering to participant_doctor_ids,
    - building a ProblemData instance.

    This function:
    1. Generates warm-start hints (seeding).
    2. Builds hard-constraint model.
    3. Adds soft constraints and objectives.
    4. Calls the OR-Tools engine to solve the model.
    5. (Optionally) applies heuristic polishing.
    6. Converts the solver solution into Assignment DTOs.
    """

    # 1) Warm-start hints (may be empty for MVP)
    #    Example hints:
    #    - heads (is_head=True) on their preferred days,
    #    - hardest slots (few available doctors),
    #    - weekend onsite+oncall combos for doctors who allow it.
    seed_hints = seeding.generate_initial_hints(problem)

    # 2) Build the hard-constraint structure (no solver calls yet)
    #    This step defines the decision variables and all "must-have" rules:
    #    - exactly 1 onsite and 1 oncall per day,
    #    - at least one specialist per day,
    #    - no double-role for the same doctor on the same day,
    #    - no assignments on unavailable days,
    #    - respect ignore_days / ignore_slots.
    hard_model = constraint_builder.build_hard_model(problem, seed_hints)

    # 3) Attach soft constraints and objective function
    #    Here we use preferences and fairness:
    #    - strong preferences for heads > specialists > residents,
    #    - rest rules between shifts,
    #    - max/target totals and weekend loads,
    #    - weekday patterns, partner preferences, etc.
    full_model = objective_builder.attach_objectives(hard_model, problem)

    # 4) Solve using OR-Tools CP-SAT (engine is the only place that imports OR-Tools)
    raw_solution = engine.build_and_solve(full_model)

    # 5) Optional: run heuristics to polish the solution (phase 3)
    #    For MVP this can simply return the original solution.
    improved_solution = heuristics.post_process(raw_solution, problem)

    # 6) Convert the final solution into a list of Assignment DTOs
    assignments = _solution_to_assignments(improved_solution, problem)

    return assignments


def _solution_to_assignments(solution, problem: ProblemData) -> List[Assignment]:
    """
    Convert the low-level solver solution (e.g. CP-SAT variable values)
    into a list of Assignment objects.

    This helper keeps the mapping logic in one place, so that:
    - services see only clean Assignment DTOs,
    - engine/constraint_builder can work with more technical structures.
    """
    # TODO: implement once engine and constraint_builder define the internal format.
    # For now we return an empty list so that the module is importable in tests.
    return []
