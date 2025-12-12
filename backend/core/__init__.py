# backend/core/__init__
"""Core solver & analytics (pure Python).
Build constraints/objectives, run CP-SAT via engine, heuristics post-process,
and compute diagnostics. No HTTP or DB imports here."""

from .feasibility import analyze_problem, compute_day_capacity  # noqa: F401

__all__ = ["analyze_problem", "compute_day_capacity"]
