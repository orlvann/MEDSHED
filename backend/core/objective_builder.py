# backend/core/objective_builder.py
"""
Attach soft constraints and objective to the hard model.

Here we:
- add rest rules between shifts,
- encode strong preferences (heads > specialists > residents),
- respect max/target totals and weekend loads,
- handle weekday patterns and partner preferences,
- implement fairness between doctors.
"""

from typing import Any

from .types import ProblemData


def attach_objectives(hard_model: Any, problem: ProblemData) -> Any:
    """
    Take the hard model and enrich it with soft constraints and an objective function.

    For MVP, this can simply return the input model unchanged.
    Later we will:
    - add penalty/bonus terms using shared functions from core.scoring,
    - prepare all data needed by engine.build_and_solve.
    """
    # TODO: extend hard_model with objective-related data.
    return hard_model
