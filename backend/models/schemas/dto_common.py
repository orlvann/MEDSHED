from typing import Iterable, List, Optional

from pydantic import BaseModel, Field
from typing_extensions import Annotated

# ---- Pagination envelope used by list endpoints ----


class PageMeta(BaseModel):
    page: int = Field(1, ge=1, description="1-based page number")
    size: int = Field(20, ge=1, le=200, description="Items per page (default 20 per contract)")
    total: int = Field(0, ge=0, description="Total number of items across all pages")


# ---- Canonical error payload (contract: {detail, code, context}) ----


class ErrorPayload(BaseModel):
    """Standard error shape returned by the API."""

    detail: str = Field(
        ...,
        description="Human-friendly error message",
        json_schema_extra={"example": "invalid credentials"},
    )
    code: str = Field(
        ...,
        description="Machine-readable error code",
        json_schema_extra={"example": "invalid_credentials"},
    )
    context: Optional[dict] = Field(
        default=None,
        description="Optional extra context for debugging (e.g., {'field': 'preferred_duty_days'})",
    )


# ---- Day helpers per contract (unique, sorted, 1..31) ----
DayInt = Annotated[int, Field(ge=1, le=31, description="Calendar day 1..31")]


def normalize_days(days: Optional[Iterable[int]]) -> List[int]:
    """Ensure days are unique, sorted and within 1..31; raise ValueError otherwise."""
    if days is None:
        return []
    s = {int(d) for d in days}
    if any(d < 1 or d > 31 for d in s):
        raise ValueError("day values must be in range 1..31")
    return sorted(s)
