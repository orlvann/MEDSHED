from datetime import datetime
from typing import Annotated, List, Optional

from annotated_types import Ge, Le
from pydantic import BaseModel, Field, field_validator, model_validator

from .common import PreferenceStatus

# ---- Helpers ---------------------------------------------------------------

MonthInt = Annotated[int, Ge(1), Le(12)]  # 1..12


def _normalize_days(days: List[int] | None) -> List[int]:
    """Ensure days are unique, sorted and within 1..31."""
    if days is None:
        return []
    s = {int(d) for d in days}
    if any(d < 1 or d > 31 for d in s):
        raise ValueError("days must be in range 1..31")
    return sorted(s)


def _validate_min_le_max(min_v: int, max_v: Optional[int], name_min: str, name_max: str) -> None:
    """Cross-field guard: min <= max (when max is set)."""
    if max_v is not None and min_v > max_v:
        raise ValueError(f"{name_min} cannot be greater than {name_max}")


# ---- DTOs -----------------------------------------------------------------


class PreferenceCreate(BaseModel):
    """Doctor (or admin on behalf) submits or creates a monthly form."""

    doctor_id: int
    year: int
    month: MonthInt

    unavailable_duty_days: List[int] = []
    unavailable_oncall_days: List[int] = []
    preferred_duty_days: List[int] = []
    preferred_oncall_days: List[int] = []

    min_duties_weekdays: int = 0
    max_duties_weekdays: int | None = None
    min_duties_weekends: int = 0
    max_duties_weekends: int | None = None
    min_oncall_weekdays: int = 0
    max_oncall_weekdays: int | None = None
    min_oncall_weekends: int = 0
    max_oncall_weekends: int | None = None

    weekend_back_to_back_allowed: bool = False
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

    # Simple scalar guards
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


class PreferenceUpdate(BaseModel):
    """
    Partial update for an existing monthly form.
    NOTE: All fields are optional. Doctor can edit own record until deadline.
    Admin can edit anytime (override). Router enforces lifecycle rules.
    """

    doctor_id: Optional[int] = None  # admin-only change
    year: Optional[int] = None
    month: MonthInt

    unavailable_duty_days: Optional[List[int]] = None
    unavailable_oncall_days: Optional[List[int]] = None
    preferred_duty_days: Optional[List[int]] = None
    preferred_oncall_days: Optional[List[int]] = None

    min_duties_weekdays: Optional[int] = None
    max_duties_weekdays: Optional[int] = None
    min_duties_weekends: Optional[int] = None
    max_duties_weekends: Optional[int] = None
    min_oncall_weekdays: Optional[int] = None
    max_oncall_weekdays: Optional[int] = None
    min_oncall_weekends: Optional[int] = None
    max_oncall_weekends: Optional[int] = None

    weekend_back_to_back_allowed: Optional[bool] = None
    preferred_partners: Optional[List[int]] = None
    comments: Optional[str] = None

    # Optional status – typically used by admin; doctor uses /submit or /revert
    status: Optional[PreferenceStatus] = None

    @field_validator(
        "unavailable_duty_days",
        "unavailable_oncall_days",
        "preferred_duty_days",
        "preferred_oncall_days",
        mode="before",
    )
    @classmethod
    def _check_days_opt(cls, v):
        # None means "unchanged"; otherwise normalize
        return None if v is None else _normalize_days(v)

    @model_validator(mode="after")
    def _cross_field_opt(self):
        # Only check min/max when both present
        pairs = [
            ("min_duties_weekdays", "max_duties_weekdays"),
            ("min_duties_weekends", "max_duties_weekends"),
            ("min_oncall_weekdays", "max_oncall_weekdays"),
            ("min_oncall_weekends", "max_oncall_weekends"),
        ]
        for mn, mx in pairs:
            mn_val = getattr(self, mn)
            mx_val = getattr(self, mx)
            if mn_val is not None and mx_val is not None and mn_val > mx_val:
                raise ValueError(f"{mn} cannot be greater than {mx}")

        # Overlap checks only if both lists provided
        if self.unavailable_duty_days is not None and self.preferred_duty_days is not None:
            if set(self.unavailable_duty_days) & set(self.preferred_duty_days):
                raise ValueError("duty days cannot be both preferred and unavailable")
        if self.unavailable_oncall_days is not None and self.preferred_oncall_days is not None:
            if set(self.unavailable_oncall_days) & set(self.preferred_oncall_days):
                raise ValueError("on-call days cannot be both preferred and unavailable")
        return self


class PreferenceRead(PreferenceCreate):
    """
    Read model mirrors the create fields + lifecycle & audit metadata.
    """

    id: int

    # Lifecycle & audit (filled by server)
    status: PreferenceStatus = Field(default=PreferenceStatus.DRAFT)
    submitted_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    updated_by_user_id: Optional[int] = Field(
        default=None, description="Last actor who modified this record"
    )


class PreferenceSummary(BaseModel):
    """
    Admin overview of monthly preference intake and coverage.
    """

    submitted: List[int] = []  # doctor ids
    missing: List[int] = []  # doctor ids
    coverageByDay: List[dict] = []  # e.g., {"day": 1, "availableDuty": 5, "availableOnCall": 3}


class PreferenceAuditEntryRead(BaseModel):
    """
    Audit trail entry for preference changes (admin override or doctor edit/submit/revert).
    """

    id: int
    preference_id: int
    actor_user_id: int
    actor_role: str  # "ADMIN" | "DOCTOR"
    action: str  # "create" | "update" | "submit" | "revert" | "admin_override"
    at: datetime
    diff: dict  # minimal JSON of changed fields (before→after or just after)
