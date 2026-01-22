# backend/core/scheduler.py
"""
High-level orchestration of the scheduling process.

This module is the "pipeline coordinator" for schedule generation.
It does NOT import OR-Tools. It only calls other core modules in the right order.

IMPORTANT IDEA: "seeding" = giving the solver a *starting suggestion* BEFORE solving
-----------------------------------------------------------------------
Seeding does NOT solve anything by itself.
It creates a set of "hints" (suggested decisions) that are attached to the CP-SAT model
*before* running the solver. This often helps CP-SAT start from a sensible direction.

Where seeding happens:
- Seeding hints are CREATED in: backend/core/seeding.py (generate_initial_hints)
- Seeding hints are ATTACHED to the CP-SAT model in: backend/core/engine.py (cp.AddHint)
- Only after hints are attached, we call: solver.Solve(cp)

Pipeline overview (who does what, in correct order)
---------------------------------------------------

PHASE 0 — Feasibility pre-check (fast, deterministic, returns detailed issues)
- File: backend/core/feasibility.py
- Function: analyze_problem(problem: ProblemData) -> List[FeasibilityIssue]
- Purpose: catch obvious impossibilities early (and return clear per-day issues).

PHASE 1 — Build HardModel (prepare all "building blocks" for the solver)
- File: backend/core/constraint_builder.py
- Function: build_hard_model(problem: ProblemData) -> HardModel
- Purpose: compute allowed_slots, active_days, ignore_* and other structural sets.
  This is the “data shape” the engine needs.

PHASE 2 — Validate head commitments (must-have input rule, stops early with issues)
- File: backend/core/seeding.py
- Function: validate_head_commitments(model: HardModel) -> List[FeasibilityIssue]
- Purpose: heads have special commitments that MUST be consistent with allowed_slots.
  If invalid -> we stop before even building the CP-SAT model.
- IMPORTANT: validation is kept here (scheduler), so we do it once (no duplicates).

PHASE 3 — Build CP-SAT model (variables + hard constraints + soft objectives)
- File: backend/core/engine.py
- Function: build_and_solve(model: HardModel) -> SolverSolution
- Purpose (build part):
  - create CP-SAT model container,
  - create decision variables,
  - add hard constraints,
  - attach soft objectives (objective_builder),
  - build ProblemData "view" for objective code.

PHASE 4 — Seeding / warm-start (attach hints BEFORE Solve)
- File: backend/core/seeding.py
- Function: generate_initial_hints(model: HardModel, problem: ProblemData) -> Dict[SeedHintKey, int]
  - Step A: seed head commitments first (as hints)
  - Step B: seed TOP-K hardest slots (fewest candidates) as hints
- File: backend/core/engine.py
  - Attaches hints to CP-SAT using cp.AddHint(...)
- KEY ORDER:
  1) build CP-SAT model (vars + constraints + objective)
  2) attach hints (seeding)
  3) call solver.Solve(cp)

PHASE 5 — Solve (CP-SAT search)
- File: backend/core/engine.py
- Call: solver.Solve(cp)
- If INFEASIBLE after search:
  - engine returns SolverSolution(status=INFEASIBLE, issues=[...])
  - including a fallback like cp_infeasible(day=0) when needed

PHASE 6 — Map solver solution -> API DTOs (Assignments)
- File: backend/core/scheduler.py
- Function: _solution_to_assignments(...)
- Policy:
  - return assignments ONLY when solver status is OK,
  - otherwise return [] (because there is no valid complete schedule to show).
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
    - ProblemData (built by services from DB data).

    Output:
    - ScheduleResult:
        * solution: SolverSolution (status + assignments + issues)
        * assignments: List[Assignment] (API-level DTOs)

    Execution order (very important):
    0) feasibility pre-check (fast, returns issues)
    1) build HardModel (allowed_slots etc.)
    2) validate head commitments (must-have; stops early with issues)
    3) engine builds CP-SAT model (vars + constraints + objectives)
    4) engine attaches seeding hints BEFORE Solve (head hints, then TOP-K hard slots)
    5) engine runs CP-SAT Solve and returns SolverSolution
    6) map solution assignments -> Assignment DTOs (only when status == OK)
    """

    # -------------------------------------------------------------------------
    # PHASE 0 — Feasibility pre-check (deterministic, cheap)
    # Module: backend/core/feasibility.py
    # Function: analyze_problem(problem)
    # If issues exist, we stop early (no OR-Tools model is built).
    # -------------------------------------------------------------------------
    issues = analyze_problem(problem)
    if issues:
        solution = SolverSolution(
            status=SolverStatus.INFEASIBLE,
            assignments=[],
            issues=issues,
        )
        return ScheduleResult(solution=solution, assignments=[])

    # -------------------------------------------------------------------------
    # PHASE 1 — Build HardModel (allowed_slots + structure for the solver)
    # Module: backend/core/constraint_builder.py
    # Function: build_hard_model(problem)
    # This is still pure Python (no OR-Tools).
    # -------------------------------------------------------------------------
    hard_model: HardModel = constraint_builder.build_hard_model(problem)

    # -------------------------------------------------------------------------
    # PHASE 2 — Validate head commitments (must-have rule)
    # Module: backend/core/seeding.py
    # Function: validate_head_commitments(model)
    #
    # Why here (scheduler) and not in engine:
    # - it needs HardModel.allowed_slots (so it must be AFTER Phase 1),
    # - scheduler is the "one place" that orchestrates early exits,
    # - we avoid doing the same validation twice (no duplicates).
    # -------------------------------------------------------------------------
    commitment_issues = seeding.validate_head_commitments(hard_model)
    if commitment_issues:
        solution = SolverSolution(
            status=SolverStatus.INFEASIBLE,
            assignments=[],
            issues=commitment_issues,
        )
        return ScheduleResult(solution=solution, assignments=[])

    # -------------------------------------------------------------------------
    # PHASE 3-5 — Build + Seed + Solve (inside engine)
    # Module: backend/core/engine.py
    # Function: build_and_solve(model)
    #
    # Engine internal order is:
    # 1) build CP-SAT model (vars + hard constraints + soft objectives)
    # 2) generate seeding hints (seeding.generate_initial_hints)
    # 3) attach hints with cp.AddHint(...)
    # 4) call solver.Solve(cp)
    # 5) if INFEASIBLE: return solution with derived issues (cp_infeasible, etc.)
    # -------------------------------------------------------------------------
    solution: SolverSolution = engine.build_and_solve(hard_model)

    # -------------------------------------------------------------------------
    # PHASE 6 — Map solver assignments -> API-level Assignment DTOs
    # We do NOT "hide issues". Issues are returned in solution.issues.
    # We only return Assignment DTOs when there is a valid complete schedule (status OK).
    # -------------------------------------------------------------------------
    assignments = _solution_to_assignments(solution, problem)
    return ScheduleResult(solution=solution, assignments=assignments)


def _solution_to_assignments(solution: SolverSolution, problem: ProblemData) -> List[Assignment]:
    """
    Convert the low-level solver solution into a list of Assignment DTOs.

    Rule:
    - If solution.status != OK -> return [] (no valid schedule to expose as assignments).
      The caller still receives full details in solution.issues.
    - If solution.status == OK -> map SolverAssignment -> Assignment and sort deterministically.
    """
    # If the solver did not produce a valid schedule, there are no assignments to publish.
    if solution.status is not SolverStatus.OK:
        return []

    assignments: List[Assignment] = []
    solver_assignments: List[SolverAssignment] = solution.assignments

    for sa in solver_assignments:
        assignments.append(
            Assignment(
                day=sa.day,
                shift_type=sa.shift_type,
                doctor_id=sa.doctor_id,
            )
        )

    # Deterministic ordering of API payloads.
    assignments.sort(key=lambda a: (a.day, a.shift_type.value, a.doctor_id))

    # `problem` is kept for future extensions (e.g., attaching extra metadata).
    return assignments
