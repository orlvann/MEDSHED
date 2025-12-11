# backend/models/common_enums.py
# Domain enums: shared by ORM, services, and DTOs.
# values: lowercase as per API contract

from enum import Enum


class UserRole(str, Enum):
    """User roles used for RBAC and account type."""

    admin = "admin"
    doctor = "doctor"
    doctor_admin = "doctor_admin"


class DoctorRole(str, Enum):
    specialist = "specialist"
    resident = "resident"


class ShiftType(str, Enum):
    # New names for public API
    onsite = "onsite"
    oncall = "oncall"


class ScheduleStatus(str, Enum):
    draft = "draft"
    published = "published"


class PreferenceStatus(str, Enum):
    missing = "missing"
    submitted = "submitted"


class PeriodStatus(str, Enum):
    past = "past"
    current = "current"
    future = "future"


class DeadlineStatus(str, Enum):
    """Deadline state for monthly preference forms."""

    open = "open"
    locked = "locked"


class RiskLevel(str, Enum):
    ok = "ok"
    alert = "alert"
    critical = "critical"


# Optional (helps diagnostics payloads)
class VersionKind(str, Enum):
    draft_checkpoint = "draft_checkpoint"
    published = "published"
