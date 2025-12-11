# backend/models/schemas/preference.py
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.models.common_enums import (
    DeadlineStatus,  # "open" | "locked"
    PeriodStatus,  # "past" | "current" | "future"
    PreferenceStatus,  # "missing" | "submitted"
)

from .dto_common import (
    DayInt,  # 1..31
    MonthInt,  # 1..12
    YearInt,  # 1900..2100
    normalize_days,
)

# ---- Helpers ---------------------------------------------------------------


def _normalize_days(days: List[int] | None) -> List[int]:
    return normalize_days(days)


def _validate_min_le_max(min_v: Optional[int], max_v: Optional[int], name_min: str, name_max: str) -> None:
    """Cross-field guard: min <= max when both are set."""
    if min_v is not None and max_v is not None and min_v > max_v:
        raise ValueError(f"{name_min} cannot be greater than {name_max}")


# ---- DTOs -----------------------------------------------------------------


class _PreferenceEditableMixin(BaseModel):
    """Editable fields used by Working PUT/Read and Checkpoint payloads."""

    # Day-level preferences (calendar days 1..31)
    unavailable_onsite_days: List[DayInt] = []
    unavailable_oncall_days: List[DayInt] = []
    preferred_onsite_days: List[DayInt] = []
    preferred_oncall_days: List[DayInt] = []

    # Monthly totals (soft constraints; some fields are future-only)
    min_onsite_total: Optional[int] = None  # future: not used in MVP
    max_onsite_total: Optional[int] = None
    target_onsite_total: Optional[int] = None

    min_oncall_total: Optional[int] = None  # future: not used in MVP
    max_oncall_total: Optional[int] = None
    target_oncall_total: Optional[int] = None

    # Weekend refinement (optional, advanced)
    max_onsite_weekends: Optional[int] = None
    target_onsite_weekends: Optional[int] = None
    max_oncall_weekends: Optional[int] = None
    target_oncall_weekends: Optional[int] = None

    # Weekday patterns (0=Monday..6=Sunday)
    preferred_onsite_weekdays: List[int] = []
    preferred_oncall_weekdays: List[int] = []
    avoid_onsite_weekdays: List[int] = []
    avoid_oncall_weekdays: List[int] = []

    # Other preferences
    allow_weekend_consecutive_onsite_oncall: bool = False
    preferred_partners: List[int] = []
    comments: Optional[str] = None

    # Normalize day lists (unique + sorted)
    @field_validator(
        "unavailable_onsite_days",
        "unavailable_oncall_days",
        "preferred_onsite_days",
        "preferred_oncall_days",
        mode="before",
    )
    @classmethod
    def _check_days(cls, v):
        return _normalize_days(v)

    @field_validator(
        "max_onsite_total",
        "max_oncall_total",
        "max_onsite_weekends",
        "max_oncall_weekends",
        mode="before",
    )
    @classmethod
    def _none_or_nonnegative(cls, v):
        if v is not None and int(v) < 0:
            raise ValueError("max values must be non-negative or null")
        return v

    @model_validator(mode="after")
    def _cross_field(self):
        # min <= max where both are set
        _validate_min_le_max(
            self.min_onsite_total,
            self.max_onsite_total,
            "min_onsite_total",
            "max_onsite_total",
        )
        _validate_min_le_max(
            self.min_oncall_total,
            self.max_oncall_total,
            "min_oncall_total",
            "max_oncall_total",
        )
        # No overlap between unavailable* and preferred* for the same shift type
        if set(self.unavailable_onsite_days) & set(self.preferred_onsite_days):
            raise ValueError("onsite days cannot be both preferred and unavailable")
        if set(self.unavailable_oncall_days) & set(self.preferred_oncall_days):
            raise ValueError("on-call days cannot be both preferred and unavailable")
        return self


class PreferenceWorkingPut(_PreferenceEditableMixin):
    """Autosave payload for PUT …/working (admin or /me)."""

    pass


class PreferenceWorkingRead(_PreferenceEditableMixin):
    """Read model for GET …/working (admin or doctor ‘me’) including hints."""

    doctor_id: int
    year: YearInt
    month: MonthInt

    status: PreferenceStatus = Field(default=PreferenceStatus.missing)
    version_id: Optional[str] = None
    submitted_at: Optional[datetime] = None
    submitted_by_role: Optional[str] = None
    submitted_by_user_id: Optional[int] = None
    last_admin_note: Optional[str] = None

    can_undo: bool = False
    can_redo: bool = False

    org_timezone: str = "Europe/Warsaw"
    period_status: PeriodStatus = Field(default=PeriodStatus.current)


class PreferenceAutosaveAck(BaseModel):
    """Response for PUT …/working (200)."""

    doctor_id: int
    year: YearInt
    month: MonthInt
    updated_at: datetime
    status: PreferenceStatus = Field(default=PreferenceStatus.missing)
    version_id: Optional[str] = None
    can_undo: bool = False
    can_redo: bool = False
    # Optional optimistic locking for UI; not required by ORM:
    lock_version: Optional[int] = None


class PreferenceCheckpointCreated(_PreferenceEditableMixin):
    """Response for POST …/checkpoint (201)."""

    doctor_id: int
    year: YearInt
    month: MonthInt

    status: PreferenceStatus = Field(default=PreferenceStatus.submitted)
    version_id: str
    submitted_at: datetime
    submitted_by_user_id: int
    submitted_by_role: str  # "admin" | "doctor"

    can_undo: bool = True
    can_redo: bool = False
    processed_at: datetime


class PreferenceRevertRead(_PreferenceEditableMixin):
    """Response for POST …/revert-last and …/revert-next (200)."""

    doctor_id: int
    year: YearInt
    month: MonthInt

    reverted_at: datetime
    version_id: str
    current_created_by_role: str
    current_created_by_user_id: int
    current_created_at: datetime
    can_undo: bool
    can_redo: bool


class PreferencesSummaryRead(BaseModel):
    """GET /api/v1/preferences/summary?year=&month="""

    year: YearInt
    month: MonthInt
    submitted: List[int] = []
    missing: List[int] = []


class PreferencesDeadlineRead(BaseModel):
    """
    Deadline configuration for a period.

    Used by:
    - GET /api/v1/preferences/deadlines/{year}/{month}

    Semantics:
    - deadline is None  -> no deadline configured for this period yet.
    - status:
        * "open"   -> edits allowed (subject to period history rules),
        * "locked" -> doctors cannot edit; admin still can.
    """

    year: YearInt
    month: MonthInt
    deadline: Optional[datetime]
    status: DeadlineStatus  # "open" | "locked"
    org_timezone: str


class PreferencesDeadlinePut(PreferencesDeadlineRead):
    """PUT-as-upsert returns the same shape; 201 if created / 200 if updated."""

    pass
