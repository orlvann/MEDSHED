# backend/core/seeding.py
"""
Warm-start / seeding logic for the solver.

This module produces "hints" for the solver:
- suggested assignments for heads on their preferred days,
- initial coverage for hardest slots (few available doctors),
- weekend combos for doctors who allow consecutive onsite+oncall.

For MVP it can return an empty structure.
"""

from typing import Any

from .types import ProblemData


def generate_initial_hints(problem: ProblemData) -> Any:
    """
    Generate warm-start hints for the solver.

    For now this returns a simple placeholder structure.
    In later iterations we will:
    - prioritize heads (is_head=True),
    - pre-assign their strong preferences where possible,
    - handle hardest-to-fill weekend slots first.
    """
    # TODO: return something more structured once the internal model is defined.
    return {}
