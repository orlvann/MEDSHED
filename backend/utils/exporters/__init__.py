"""Export pipelines (XLSX/PDF/ICS).
Consume DTOs (not ORM) so exports work from API or CLI consistently."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class DoctorExportData:
    """All data needed to build an export file for one doctor's monthly schedule."""

    doctor_id: int
    first_name: str
    last_name: str
    role: str  # "specialist" | "resident"
    year: int
    month: int
    org_timezone: str  # e.g. "Europe/Warsaw"
    assignments: List[dict] = field(default_factory=list)
    # Each dict: {"day": int, "shift_type": str}  (str values: "onsite" | "oncall")


@dataclass
class TeamExportData:
    """All data needed to build an export file for the full team schedule."""

    year: int
    month: int
    org_timezone: str
    assignments: List[dict] = field(default_factory=list)
    # Each dict: {"day": int, "shift_type": str, "doctor_name": str, "doctor_last_name": str}
    # doctor_name = full "Dr. First Last" (used by ICS), doctor_last_name = surname only (PDF/XLSX)
    shift_type_filter: str | None = None
    # "onsite", "oncall", or None (show both columns in PDF/XLSX)


@dataclass
class ExportResult:
    """Binary payload returned by builders, ready for HTTP streaming."""

    content: bytes
    content_type: str
    filename: str
