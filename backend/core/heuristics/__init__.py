# backend/core/heuristics/__init__.py
"""
Heuristic post-processing algorithms.
Small, feasible moves to polish solver output (speed > exact optimality).

For now, we only expose a simple pass-through helper.
Later we can add:
- greedy search,
- simulated annealing,
- local search operators, etc.
"""

from typing import Any

from backend.core.types import ProblemData


def post_process(solution: Any, problem: ProblemData) -> Any:
    """
    Heuristic polishing step (phase 3 of the scheduler).

    MVP: no changes, just return the original solver output.
    """
    return solution
