# backend/models/schemas/schedule.py
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from backend.models.common_enums import (
    DoctorRole,  # "specialist" | "resident"
    ShiftType,  # "onsite" | "oncall"
)

# IMPORTANT: we need DiagnosticsRead at runtime for Pydantic to resolve
# forward refs during model_rebuild(). This import is safe (no circular deps),
# diagnostics.py does not import schedule.py.
from .diagnostics import DiagnosticsRead  # noqa: F401
from .dto_common import (
    DayInt,  # 1..31 (validated)
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
