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
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from backend.models.common_enums import (
    DoctorRole,  # "specialist" | "resident"
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


class DoctorSnapshotRead(BaseModel):
    """Frozen doctor inputs used for schedule creation and later diagnostics/publish validation.

    This must NOT depend on the live Doctor table because doctor data can change over time.
    """

    role: DoctorRole
    is_head: bool
    display_name: str
    is_active_at_snapshot: bool


class InputsSnapshotRead(BaseModel):
    """Frozen inputs used to compute schedule and diagnostics.

    Notes:
    - JSON object keys are always strings, so we accept "123" and coerce to 123.
    - In Python code we want dict[int, ...] for clarity and type safety.
    """

    doctors: Dict[int, DoctorSnapshotRead] = Field(default_factory=dict)
    preference_version_id_by_doctor: Dict[int, Optional[int]] = Field(default_factory=dict)

    @field_validator("doctors", mode="before")
    @classmethod
    def _coerce_doctors_keys_to_int(cls, v):
        # Accept JSON keys like "123" and coerce them to int keys.
        if v is None:
            return {}
        if isinstance(v, dict):
            return {int(k): val for k, val in v.items()}
        return v

    @field_validator("preference_version_id_by_doctor", mode="before")
    @classmethod
    def _coerce_pref_keys_to_int(cls, v):
        # Accept JSON keys like "123" and coerce them to int keys.
        if v is None:
            return {}
        if isinstance(v, dict):
            return {int(k): val for k, val in v.items()}
        return v


class SchedulePayload(BaseModel):
    """Versioned snapshot payload (used for draft checkpoints & published versions)."""

    participant_doctor_ids: List[int] = Field(default_factory=list)
    assignments: List[Assignment] = Field(default_factory=list)

    # IMPORTANT:
    # - Optional for backward compatibility (older DB versions have no snapshot yet).
    # - New versions should include it, but backfill will be done in later steps.
    inputs_snapshot: Optional[InputsSnapshotRead] = Field(
        default=None,
        description="Frozen inputs used to create the schedule (doctors + preference version ids).",
    )

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

    # Keep the same snapshot available on working (deterministic diagnostics & publish validation).
    inputs_snapshot: Optional[InputsSnapshotRead] = Field(
        default=None,
        description="Frozen inputs used to create the schedule (doctors + preference version ids).",
    )


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


class HeadCommitmentResolution(BaseModel):
    """
    Admin's manual resolution for a head commitment conflict.

    Meaning:
    - For a conflicting slot (day + shift_type), admin selects which head keeps this commitment.
    - Service will remove this day from other heads' preferred_*_days for the same shift type
      (only for the purpose of this generation run).
    """

    day: DayInt
    shift_type: ShiftType
    chosen_head_id: int


class ScheduleGenerateRequest(BaseModel):
    """POST /api/v1/schedules/generate"""

    year: YearInt
    month: MonthInt
    participant_doctor_ids: List[int] = Field(default_factory=list)

    # FINAL POLICY:
    # - ignore_days is removed from the whole flow.
    # - Only individual slots can be ignored.
    ignore_slots: List[IgnoreSlot] = Field(default_factory=list)

    # Optional: provided only when FE resolves "multiple heads want same slot" conflicts.
    head_commitment_resolutions: List[HeadCommitmentResolution] = Field(
        default_factory=list,
        description=(
            "Manual conflict resolutions for head commitments. "
            "For each conflicting (day, shift_type) slot, choose which head keeps the commitment."
        ),
        examples=[
            [
                {"day": 5, "shift_type": "onsite", "chosen_head_id": 101},
                {"day": 12, "shift_type": "oncall", "chosen_head_id": 102},
            ]
        ],
    )

    @field_validator("head_commitment_resolutions", mode="before")
    @classmethod
    def _normalize_head_commitment_resolutions(cls, v):
        """
        Normalize resolutions deterministically:
        - accept None as empty list,
        - keep last resolution for the same (day, shift_type),
        - sort by (day, shift_type.value, chosen_head_id).

        IMPORTANT:
        - if any required field is missing -> return raw v so Pydantic can raise a clear error.
        """
        if v is None:
            return []
        if not isinstance(v, list):
            return v

        # Keep the LAST resolution for a given (day, shift_type) (deterministic).
        dedup: Dict[tuple[int, str], Dict[str, Any]] = {}

        for item in v:
            if isinstance(item, dict):
                day_raw = item.get("day")
                st = item.get("shift_type")
                chosen_raw = item.get("chosen_head_id")
                if day_raw is None or st is None or chosen_raw is None:
                    return v

                day = int(day_raw)
                st_val = str(getattr(st, "value", st))
                dedup[(day, st_val)] = {
                    "day": day,
                    "shift_type": st,
                    "chosen_head_id": int(chosen_raw),
                }
                continue

            # Object-like input (e.g., Pydantic model instance)
            day_raw = getattr(item, "day", None)
            st = getattr(item, "shift_type", None)
            chosen_raw = getattr(item, "chosen_head_id", None)
            if day_raw is None or st is None or chosen_raw is None:
                return v

            day = int(day_raw)
            st_val = str(getattr(st, "value", st))
            dedup[(day, st_val)] = {
                "day": day,
                "shift_type": st,
                "chosen_head_id": int(chosen_raw),
            }

        out = list(dedup.values())

        # Sort deterministically.
        out.sort(
            key=lambda x: (
                x["day"],
                str(getattr(x["shift_type"], "value", x["shift_type"])),
                x["chosen_head_id"],
            )
        )
        return out


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
