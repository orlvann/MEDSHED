from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

# ---- Shared enums for strong typing and clear contracts ----


class Role(str, Enum):
    ADMIN = "ADMIN"
    DOCTOR = "DOCTOR"


class DoctorRole(str, Enum):
    SPECIALIST = "SPECIALIST"
    RESIDENT = "RESIDENT"


class ShiftType(str, Enum):
    ON_DUTY = "OnDuty"
    ON_CALL = "OnCall"


class ScheduleStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class PreferenceStatus(str, Enum):
    """Lifecycle of a monthly preference form."""

    DRAFT = "draft"  # editable by doctor until deadline
    SUBMITTED = "submitted"  # doctor clicked submit;
    # still editable until deadline (revert to draft on edit)
    LOCKED = "locked"  # system-enforced after deadline (admin override only)


# ---- Pagination envelope used by list endpoints ----


class PageMeta(BaseModel):
    page: int = Field(1, ge=1, description="1-based page number")
    size: int = Field(50, ge=1, le=200, description="Items per page")
    total: int = Field(0, ge=0, description="Total number of items across all pages")


# ---- Canonical error payload (optional helper) ----


class ErrorPayload(BaseModel):
    """Standard error shape returned by the API."""

    code: str = Field(
        ...,
        description="Machine-readable error code",
        json_schema_extra={"example": "invalid_credentials"},
    )
    message: str = Field(
        ...,
        description="Human-friendly error message",
        json_schema_extra={"example": "Invalid email or password"},
    )
    details: Optional[dict] = Field(
        default=None,
        description="Optional extra context for debugging",
    )
