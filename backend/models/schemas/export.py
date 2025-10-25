from typing import Annotated, Literal, Optional

from annotated_types import Ge, Le
from pydantic import BaseModel, Field

# Month 1..12 as in the contract
MonthInt = Annotated[int, Ge(1), Le(12)]


class ScheduleExportQuery(BaseModel):
    """
    Query params for:
      GET /api/v1/schedules/export
      ?year=YYYY&month=MM
      &mode=draft|published
      &format=xlsx|pdf|ics[&doctor_id=]

    Note: The endpoint returns a binary stream with proper Content-Type and Content-Disposition.
    No JSON body in the response.
    """

    year: int
    month: MonthInt
    mode: Literal["draft", "published"]
    format: Literal["xlsx", "pdf", "ics"]
    doctor_id: Optional[int] = Field(
        default=None,
        description=(
            "For ICS exports only. "
            "Admin may export ICS for a specific doctor (required); "
            "Doctors exporting ICS must be forced to their own id "
            "(server will ignore/forbid others)."
        ),
    )
