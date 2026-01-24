# backend/models/schemas/schedule.py
# Data Transfer Objects for the Schedules module (framework-agnostic).
# These models define the public API shapes used by /api/v1/schedules* endpoints.
#
# Key design goals:
# - Keep routers thin: all shapes are here, all future business logic will live in services.
# - Deterministic payloads: every write/snapshot must go through a single normalization pipeline
#   (see backend/utils/normalization.py) so that ordering and duplicates are stable/removed.
# - Optimistic concurrency (hard OCC) is planned post-MVP. We already expose lock_version in
#   reads/ACKs and accept if_match_lock_version in PUT so the FE can start echoing it today.
# - Period View must always be representable as a unified shape, including an "empty skeleton"
#   when no data exists yet for a period.
#
# Pydantic: v2-compatible models (BaseModel). Where lists/dicts are used, we always rely on
# Field(default_factory=...) to avoid shared mutable defaults.

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from backend.models.common_enums import (
    PeriodStatus,  # "past" | "current" | "future"
    ScheduleStatus,  # "draft" | "published"
    ShiftType,  # "onsite" | "oncall"
)

# IMPORTANT: we need DiagnosticsRead at runtime for Pydantic to resolve
# forward refs during model_rebuild(). This import is safe (no circular deps),
# diagnostics.py does not import schedule.py.
from .diagnostics import DiagnosticsRead  # noqa: F401
from .dto_common import (
    DayInt,  # 1..31 (validated)
    MonthInt,  # canonical 1..12 month
    YearInt,  # canonical 1900..2100 year (zgodnie z dto_common)
    normalize_days,  # helper for dedup/sort/validation of day lists
)

# ------------------------------ Core small blocks ------------------------------


class Assignment(BaseModel):
    """One assignment cell in the schedule grid.

    Deterministic normalization rule (enforced in services on write/snapshot):
    - Always sort assignments by (day, shift_type, doctor_id).
    - Deduplicate equal triplets.
    - The DTO only declares shape; normalization happens centrally in utils/normalization.py.
    """

    day: DayInt
    shift_type: ShiftType
    doctor_id: int


class SchedulePayload(BaseModel):
    """Versioned snapshot payload (used for draft checkpoints & published versions)."""

    participant_doctor_ids: List[int] = Field(default_factory=list)
    assignments: List[Assignment] = Field(default_factory=list)
    # meta.labels must exist; meta.exceptions is optional, untyped metadata for now
    meta: Dict = Field(default_factory=lambda: {"labels": []})


# ------------------------------ Working draft (GET/PUT) ------------------------------


class ScheduleWorkingRead(BaseModel):
    """Working draft as returned by GET /api/v1/schedules/{year}/{month}/working
    or embedded within Period View.

    Notes:
    - 'exists' tells FE whether a persisted working entity exists. For an empty skeleton
      we return exists=False and keep arrays empty.
    - 'lock_version' is reserved for hard OCC (not enforced in MVP). FE should echo it
      via if_match_lock_version in PUT requests once available.
    """

    year: YearInt
    month: MonthInt
    exists: bool = True
    participant_doctor_ids: List[int] = Field(default_factory=list)
    assignments: List[Assignment] = Field(default_factory=list)
    meta: Dict = Field(default_factory=lambda: {"labels": []})
    updated_at: Optional[datetime] = None
    lock_version: Optional[int] = None


class ScheduleWorkingPut(BaseModel):
    """Request body for PUT /api/v1/schedules/{year}/{month}/working (autosave).

    Behavior:
    - Overwrites the working buffer only (no checkpoint creation).
    - Services perform deterministic normalization on 'assignments' before persisting.
    - 'if_match_lock_version' is accepted (optional) for future hard OCC enforcement.
    """

    assignments: List[Assignment] = Field(default_factory=list)
    meta: Optional[Dict] = None

    # MVP: not enforced yet, but present so FE can start echoing it.
    if_match_lock_version: Optional[int] = None


class ScheduleWorkingAck(BaseModel):
    """Lean acknowledgment after PUT /working.

    Why small ACK (vs returning full working state):
    - Autosave is frequent; ACK avoids sending full payload back.
    - It returns the new lock_version so FE can echo it on the next PUT.
    """

    year: YearInt
    month: MonthInt
    updated_at: datetime
    lock_version: Optional[int] = None


# ------------------------------ Period View (unified) ------------------------------


class ScheduleDraftView(BaseModel):
    """Draft pointer block used in Period View and checkpoint responses."""

    version_id: Optional[str] = None
    checkpoints_count: int = 0
    can_undo: bool = False
    can_redo: bool = False
    payload: Optional[SchedulePayload] = None


class SchedulePublishedView(BaseModel):
    """Published pointer block used in Period View and publish responses."""

    version_id: Optional[str] = None
    publications_count: int = 0
    can_undo: bool = False
    can_redo: bool = False
    # Lightweight audit metadata for published snapshots (optional on read).
    # Kept minimal for MVP; can be replaced with a stronger model later.
    audit: Optional[Dict] = None
    payload: Optional[SchedulePayload] = None


class _ViewHint(BaseModel):
    """UI hints for the tab; non-binding but helpful defaults."""

    default_mode: Literal["draft", "published"] = "draft"
    toggle_available: bool = True


class SchedulesPeriodViewRead(BaseModel):
    """GET /api/v1/schedules/{year}/{month} (Admin tab — Period View).

    This shape must be returnable even when no data exists yet (empty skeleton).
    In that case:
    - working.exists = False
    - draft.version_id = None
    - published.version_id = None
    - diagnostics = None
    """

    year: YearInt
    month: MonthInt
    org_timezone: str = "Europe/Warsaw"
    period_status: PeriodStatus = PeriodStatus.current
    view: _ViewHint = Field(default_factory=_ViewHint)

    working: ScheduleWorkingRead
    draft: ScheduleDraftView
    published: SchedulePublishedView
    diagnostics: Optional["DiagnosticsRead"] = None  # may be absent when no version present


# ------------------------------ Generate ------------------------------


class IgnoreSlot(BaseModel):
    """A single slot to be ignored by the generator (day+shift_type)."""

    day: DayInt
    shift_type: ShiftType


class ScheduleGenerateRequest(BaseModel):
    """POST /api/v1/schedules/generate"""

    year: YearInt
    month: MonthInt
    participant_doctor_ids: List[int] = Field(default_factory=list)
    ignore_days: List[DayInt] = Field(default_factory=list)
    ignore_slots: List[IgnoreSlot] = Field(default_factory=list)

    @field_validator("ignore_days", mode="before")
    @classmethod
    def _dedupe_days(cls, v):
        # Normalize: unique, sorted, and within 1..31; raises ValueError otherwise.
        return normalize_days(v)


class ScheduleGenerateCreated(BaseModel):
    """201 result for Generate. Returns working + first draft checkpoint + diagnostics."""

    year: YearInt
    month: MonthInt
    status: ScheduleStatus = ScheduleStatus.draft
    working: ScheduleWorkingRead
    draft: ScheduleDraftView
    diagnostics: "DiagnosticsRead"


# ------------------------------ Draft checkpoint / revert ------------------------------


class ScheduleCheckpointRequest(BaseModel):
    """POST /api/v1/schedules/{year}/{month}/checkpoint

    Only optional metadata (e.g., note). The checkpoint snapshot is taken
    from the current normalized working by the service.
    """

    note: Optional[str] = None


class ScheduleCheckpointCreated(BaseModel):
    """201 after checkpoint creation."""

    year: YearInt
    month: MonthInt
    draft: ScheduleDraftView
    diagnostics: "DiagnosticsRead"


class ScheduleRevertRead(BaseModel):
    """200 after draft UNDO/REDO (pointer move + working overwrite).

    The service replaces working with the checkpoint's normalized payload.
    """

    year: YearInt
    month: MonthInt
    draft: ScheduleDraftView
    working: ScheduleWorkingRead
    diagnostics: "DiagnosticsRead"


# ------------------------------ Publish ------------------------------


class AcceptedException(BaseModel):
    """User-acknowledged exception to a hard rule when forcing publish."""

    code: str
    justification: str


class SchedulePublishRequest(BaseModel):
    """POST /api/v1/schedules/{year}/{month}/publish"""

    force: bool = False
    note: Optional[str] = None
    accepted_exceptions: List[AcceptedException] = Field(default_factory=list)


class SchedulePublishCreated(BaseModel):
    """201 after successful publish."""

    year: YearInt
    month: MonthInt
    published: SchedulePublishedView


class SchedulePublishedRevertRead(BaseModel):
    """200 after published rollback/redo (pointer move)."""

    year: YearInt
    month: MonthInt
    published: SchedulePublishedView


# ------------------------------ Doctor path (read-only views) ------------------------------


class SchedulePublishedRead(BaseModel):
    """GET /api/v1/schedules/{year}/{month}/published (Doctor path — read-only)."""

    year: YearInt
    month: MonthInt
    org_timezone: str = "Europe/Warsaw"
    period_status: PeriodStatus = PeriodStatus.current
    published: SchedulePublishedView


class MyAssignment(BaseModel):
    """A simplified view of assignments for a specific doctor."""

    day: DayInt
    shift_type: ShiftType


class MyAssignmentsRead(BaseModel):
    """GET /api/v1/schedules/{year}/{month}/my-assignments"""

    doctor_id: int
    year: YearInt
    month: MonthInt
    assignments: List[MyAssignment] = Field(default_factory=list)


# ------------------------------ Pydantic forward refs ------------------------------

# Allow forward-referenced types (DiagnosticsRead) to resolve at runtime.
# This must be called after class definitions.
SchedulesPeriodViewRead.model_rebuild()
ScheduleGenerateCreated.model_rebuild()
ScheduleCheckpointCreated.model_rebuild()
ScheduleRevertRead.model_rebuild()
SchedulePublishCreated.model_rebuild()
SchedulePublishedRevertRead.model_rebuild()
SchedulePublishedRead.model_rebuild()
