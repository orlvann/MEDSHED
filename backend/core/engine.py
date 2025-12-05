# backend/core/engine.py
"""
Adapter for the OR-Tools CP-SAT solver.

This is the ONLY place where we directly import OR-Tools.
Everything else in core works with plain Python structures.
"""

from typing import Any, Dict


def build_and_solve(model: Any) -> Dict:
    """
    Translate the abstract model into OR-Tools CP-SAT,
    run the solver, and return a low-level solution object.

    For MVP this can return a very simple placeholder that
    _solution_to_assignments() can understand.
    """
    # TODO: implement OR-Tools integration.
    # For now we return an empty solution structure.
    return {"status": "NOT_IMPLEMENTED", "assignments": []}
