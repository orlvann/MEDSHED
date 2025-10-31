# backend/models/schemas/dto_common.py
# -----------------------------------------------------------------------------
# Common, framework-agnostic DTO helpers used across multiple schemas.
# Keep this file tiny and dependency-free to avoid circular imports.
# -----------------------------------------------------------------------------

from __future__ import annotations

from typing import Iterable, List, Optional

from pydantic import BaseModel, Field

# IMPORTANT:
# - In Python 3.11+, Annotated lives in 'typing'. Using typing_extensions keeps
#   this file compatible if someone runs it under 3.10 in the future.
try:
    from typing import Annotated  # py311+
except ImportError:  # pragma: no cover
    from typing_extensions import Annotated  # py310 fallback


# -----------------------------------------------------------------------------
# Pagination envelope used by list endpoints
# -----------------------------------------------------------------------------


class PageMeta(BaseModel):
    page: int = Field(1, ge=1, description="1-based page number.")
    size: int = Field(
        20,
        ge=1,
        le=200,
        description="Items per page (default 20; server hard cap 200).",
    )
    total: int = Field(0, ge=0, description="Total number of matching items across all pages.")


# -----------------------------------------------------------------------------
# Canonical error payload (contract: {detail, code, context})
# -----------------------------------------------------------------------------


class ErrorPayload(BaseModel):
    """Standard error shape returned by the API."""

    detail: str = Field(
        ...,
        description="Human-friendly error message.",
        json_schema_extra={"example": "invalid credentials"},
    )
    code: str = Field(
        ...,
        description="Machine-readable error code.",
        json_schema_extra={"example": "invalid_credentials"},
    )
    context: Optional[dict] = Field(
        default=None,
        description="Optional extra context for debugging " "(e.g., {'field': 'preferred_duty_days'}).",
    )


def make_error(code: str, *, detail: str | None = None, context: dict | None = None) -> dict:
    """
    Build a standardized error dict matching ErrorPayload.
    Usage:
      raise HTTPException(status_code=409, detail=make_error("edit_conflict"))
      raise HTTPException(status_code=404, detail=make_error("not_found", context={"entity":"schedule"}))
    """
    payload = ErrorPayload(detail=detail or code, code=code, context=context)
    return payload.model_dump()


# -----------------------------------------------------------------------------
# Year/Month/Day helpers per contract
# Use these aliases inside schemas to keep validation consistent everywhere.
# -----------------------------------------------------------------------------

YearInt = Annotated[int, Field(ge=1900, le=2100, description="Calendar year 1900..2100")]
MonthInt = Annotated[int, Field(ge=1, le=12, description="Calendar month 1..12")]
DayInt = Annotated[int, Field(ge=1, le=31, description="Calendar day 1..31")]


# -----------------------------------------------------------------------------
# Normalizers used by preference/schedule day lists
# -----------------------------------------------------------------------------


def normalize_days(days: Optional[Iterable[int]]) -> List[int]:
    """
    Ensure days are unique, sorted and within 1..31.
    Returns a *new* list. For None returns [].
    Raises ValueError if any element is outside 1..31.

    Rationale:
    - Deterministic ordering prevents 'false diffs' in checkpoints/publish.
    - Uniqueness keeps payloads compact and predictable.
    """
    if days is None:
        return []

    # Cast to int explicitly to tolerate inputs like ["1", 2, 2]
    cleaned = {int(d) for d in days}
    if any(d < 1 or d > 31 for d in cleaned):
        raise ValueError("day values must be in range 1..31")

    return sorted(cleaned)


# What we publicly export from this module (helps editor auto-complete).
__all__ = [
    "PageMeta",
    "ErrorPayload",
    "make_error",
    "YearInt",
    "MonthInt",
    "DayInt",
    "normalize_days",
]
