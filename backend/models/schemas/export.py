# backend/models/schemas/export.py
# -----------------------------------------------------------------------------
# Export DTOs — query shape for schedule exports and (optionally) a stub read
# used while the endpoint still returns JSON instead of a binary stream.
# -----------------------------------------------------------------------------

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

# Re-use canonical scalar types (keep contract consistent everywhere)
from backend.models.schemas.dto_common import MonthInt, YearInt


class ScheduleExportQuery(BaseModel):
    """
    Query parameters for:
      GET /api/v1/schedules/export
        ?year=YYYY
        &month=MM
        &mode=draft|published
        &format=xlsx|pdf
        [&doctor_id=]

    NOTE (MVP): the endpoint currently returns a JSON stub (see ScheduleExportStubRead).
    POST-MVP: the endpoint SHOULD stream a binary file with proper Content-Type and
    Content-Disposition headers; no JSON body then.
    """

    year: YearInt
    month: MonthInt
    mode: Literal["draft", "published"] = Field(
        ...,
        description="Export from the current pointer: 'draft' (latest checkpoint) or 'published'.",
    )
    # ICS is intentionally NOT exposed yet to match the current router implementation.
    format: Literal["xlsx", "pdf"] = Field(
        ...,
        description="Output file format. ICS is planned post-MVP.",
    )
    doctor_id: Optional[int] = Field(
        default=None,
        description=(
            "Reserved for ICS exports. " "For ICS, doctors export only their own calendar; admins may specify a doctor."
        ),
    )


class ScheduleExportStubRead(BaseModel):
    """
    Temporary JSON response used in MVP while the real endpoint does not yet
    stream a file. This mirrors what the router currently returns.
    """

    detail: str = Field(..., json_schema_extra={"example": "stub: export stream here"})
    year: YearInt
    month: MonthInt
    mode: Literal["draft", "published"]
    format: Literal["xlsx", "pdf"]
    doctor_id: Optional[int] = None


__all__ = [
    "ScheduleExportQuery",
    "ScheduleExportStubRead",
]
