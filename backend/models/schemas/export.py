from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ExportOptions(BaseModel):
    format: Literal["xlsx", "pdf"] = "xlsx"
    include_diagnostics: bool = True
    include_details: bool = True


class ExportResponse(BaseModel):
    schedule_id: int
    content_type: Literal[
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/pdf",
    ] = Field(..., description="MIME type of the generated file")
    generated_at: datetime
    download_url: str | None = None
    size_bytes: int | None = None
