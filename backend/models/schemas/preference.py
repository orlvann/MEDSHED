from datetime import datetime
from typing import Annotated, List, Optional

from annotated_types import Ge, Le
from pydantic import BaseModel, Field, field_validator, model_validator

from backend.models.common_enums import (
    PeriodStatus,  # "past" | "current" | "future"
    PreferenceStatus,  # "missing" | "submitted"
    RiskLevel,  # "ok" | "alert" | "critical"
)

from .doctor import DoctorMini
from .dto_common import (
    DayInt,  # 1..31
    normalize_days,
)

# ---- Helpers ---------------------------------------------------------------

MonthInt = Annotated[int, Ge(1), Le(12)]  # 1..12


# Re-export local alias for readability in validators (uses common.normalize_days)
def _normalize_days(days: List[int] | None) -> List[int]:
    return normalize_days(days)


def _validate_min_le_max(min_v: int, max_v: Optional[int], name_min: str, name_max: str) -> None:
    """Cross-field guard: min <= max (when max is set)."""
    if max_v is not None and min_v > max_v:
        raise ValueError(f"{name_min} cannot be greater than {name_max}")


# ---- DTOs -----------------------------------------------------------------


class _PreferenceEditableMixin(BaseModel):
    """Editable fields used by Working PUT/Read and Checkpoint payloads."""

    unavailable_duty_days: List[DayInt] = []
    unavailable_oncall_days: List[DayInt] = []
    preferred_duty_days: List[DayInt] = []
    preferred_oncall_days: List[DayInt] = []

    min_duties_weekdays: int = 0
    max_duties_weekdays: Optional[int] = None
    min_duties_weekends: int = 0
    max_duties_weekends: Optional[int] = None
    min_oncall_weekdays: int = 0
    max_oncall_weekdays: Optional[int] = None
    min_oncall_weekends: int = 0
    max_oncall_weekends: Optional[int] = None

    weekend_back_to_back_allowed: bool = True
    preferred_partners: List[int] = []
    comments: Optional[str] = None

    # Normalize day lists (unique + sorted)
    @field_validator(
        "unavailable_duty_days",
        "unavailable_oncall_days",
        "preferred_duty_days",
        "preferred_oncall_days",
        mode="before",
    )
    @classmethod
    def _check_days(cls, v):
        return _normalize_days(v)

    @field_validator(
        "max_duties_weekdays",
        "max_duties_weekends",
        "max_oncall_weekdays",
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
        # min <= max where max is set
        _validate_min_le_max(
            self.min_duties_weekdays,
            self.max_duties_weekdays,
            "min_duties_weekdays",
            "max_duties_weekdays",
        )
        _validate_min_le_max(
            self.min_duties_weekends,
            self.max_duties_weekends,
            "min_duties_weekends",
            "max_duties_weekends",
        )
        _validate_min_le_max(
            self.min_oncall_weekdays,
            self.max_oncall_weekdays,
            "min_oncall_weekdays",
            "max_oncall_weekdays",
        )
        _validate_min_le_max(
            self.min_oncall_weekends,
            self.max_oncall_weekends,
            "min_oncall_weekends",
            "max_oncall_weekends",
        )
        # no overlap between unavailable_* and preferred_* for the same shift type
        if set(self.unavailable_duty_days) & set(self.preferred_duty_days):
            raise ValueError("duty days cannot be both preferred and unavailable")
        if set(self.unavailable_oncall_days) & set(self.preferred_oncall_days):
            raise ValueError("on-call days cannot be both preferred and unavailable")
        return self


class PreferenceWorkingPut(_PreferenceEditableMixin):
    """
    Autosave payload for:
    PUT /api/v1/preferences/{year}/{month}/{doctor_id}/working
    PUT /api/v1/preferences/{year}/{month}/me/working
    """

    # only editable fields – no ids here
    pass


class PreferenceWorkingRead(_PreferenceEditableMixin):
    """
    Read model for GET .../working (admin or doctor ‘me’) including hints.
    Mirrors contract examples.
    """

    doctor_id: int
    year: int
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
    year: int
    month: MonthInt
    updated_at: datetime
    status: PreferenceStatus = Field(default=PreferenceStatus.missing)
    version_id: Optional[str] = None
    can_undo: bool = False
    can_redo: bool = False


class PreferenceCheckpointCreated(_PreferenceEditableMixin):
    """
    Response for POST …/checkpoint (201).
    """

    doctor_id: int
    year: int
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
    """
    Response for POST …/revert-last and …/revert-next (200).
    """

    doctor_id: int
    year: int
    month: MonthInt

    reverted_at: datetime
    version_id: str
    current_created_by_role: str
    current_created_by_user_id: int
    current_created_at: datetime
    can_undo: bool
    can_redo: bool


class PreferencesSummaryRead(BaseModel):
    """
    GET /api/v1/preferences/summary?year=&month=
    """

    year: int
    month: MonthInt
    submitted: List[int] = []
    missing: List[int] = []
    last_update_at: datetime


class PreferencesDeadlineRead(BaseModel):
    year: int
    month: MonthInt
    deadline: datetime
    status: str  # "open" | "locked"
    org_timezone: str


class PreferencesDeadlinePut(PreferencesDeadlineRead):
    """PUT-as-upsert returns the same shape; 201 if created / 200 if updated."""

    pass


# -----------------------------------------------------------------------------
# Availability (pre-flight coverage) — colocated here to avoid a new file
# Endpoints:
#   GET /api/v1/availability/overview?year=&month=
#   GET /api/v1/availability/{year}/{month}/{day}
# -----------------------------------------------------------------------------


class AvailabilityDaySummary(BaseModel):
    day: DayInt
    available_specialists: int
    available_residents: int
    risk: RiskLevel  # "ok" | "alert" | "critical"


class AvailabilityOverviewRead(BaseModel):
    days: list[AvailabilityDaySummary] = []


class AvailabilityDayRead(BaseModel):
    day: DayInt
    specialists: list[DoctorMini] = []
    residents: list[DoctorMini] = []
    risk: RiskLevel
