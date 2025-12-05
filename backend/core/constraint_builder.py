# backend/core/constraint_builder.py
"""
Build the hard-constraint part of the model (no objective yet).

This module:
- defines decision variables,
- enforces all hard rules:
  * 1 onsite + 1 oncall per day,
  * at least one specialist per day,
  * no double-role per day per doctor,
  * no assignments on unavailable days,
  * ignore_days / ignore_slots.
"""

from typing import Any

from .types import ProblemData


def build_hard_model(problem: ProblemData, seed_hints: Any) -> Any:
    """
    Build an abstract hard-constraint model.

    For now this returns a placeholder object.
    Later it will:
    - create the internal structures that engine.build_and_solve understands
      (e.g. CP-SAT variables and lists of constraints).
    """
    # TODO: define and return a proper model structure.
    return {"problem": problem, "seed_hints": seed_hints}
