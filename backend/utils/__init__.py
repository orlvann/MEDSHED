# backend/utils/__init__.py

"""Shared helpers (validators, normalization, time utilities).
Pure utilities; avoid importing FastAPI or ORM here where possible.
"""

# Re-export selected helpers for convenient import paths:
# from backend.utils import normalize_assignments, now_utc, ...
from .normalization import normalize_assignments, normalize_meta  # noqa: F401
from .timez import ORG_TZ, days_in_month, get_period_status, is_period_closed, now_utc  # noqa: F401

__all__ = [
    # normalization
    "normalize_assignments",
    "normalize_meta",
    # time utilities
    "ORG_TZ",
    "get_period_status",
    "is_period_closed",
    "now_utc",
    "days_in_month",
]
