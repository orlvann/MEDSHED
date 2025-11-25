# backend/models/schemas/__init__.py
"""
Pydantic DTOs (request/response shapes).
Validate input early, serialize output consistently, and power OpenAPI docs.

Note:
- Domain enums live in `backend.models.common_enums` (single source of truth).
- This package re-exports commonly used DTOs for convenient imports elsewhere.
"""

# backend/models/schemas/__init__.py
# Public re-exports of Pydantic DTOs for short imports across the codebase.
# Linters: names listed in __all__ are intentional exports.

# Enums (domain-level, shared by ORM/DTOs/services)
from backend.models.common_enums import (
    DoctorRole,
    PeriodStatus,
    PreferenceStatus,
    RiskLevel,
    Role,
    ScheduleStatus,
    ShiftType,
)

# Auth / User
from .auth import LoginRequest, SetPasswordRequest, SetPasswordResponse, TokenResponse

# Availability
from .availability import (
    AvailabilityDayRead,
    AvailabilityDaySummary,
    AvailabilityOverviewRead,
    AvailabilityRiskLevel,
)

# Diagnostics
from .diagnostics import DiagnosticsRead, DiagnosticsSummary

# Doctors
from .doctor import DoctorCreate, DoctorList, DoctorMini, DoctorPut, DoctorRead

# DTO helpers / error payloads
from .dto_common import ErrorPayload

# Export (query DTO; response is a file stream)
from .export import ScheduleExportQuery

# Preferences
from .preference import (
    PreferenceAutosaveAck,
    PreferenceCheckpointCreated,
    PreferenceRevertRead,
    PreferencesDeadlinePut,
    PreferencesDeadlineRead,
    PreferencesSummaryRead,
    PreferenceWorkingPut,
    PreferenceWorkingRead,
)

# Schedules
from .schedule import (
    Assignment,
    IgnoreSlot,
    MyAssignment,
    MyAssignmentsRead,
    ScheduleCheckpointCreated,
    ScheduleCheckpointRequest,
    ScheduleDraftView,
    ScheduleGenerateCreated,
    ScheduleGenerateRequest,
    SchedulePayload,
    SchedulePublishCreated,
    SchedulePublishedRead,
    SchedulePublishedRevertRead,
    SchedulePublishedView,
    SchedulePublishRequest,
    ScheduleRevertRead,
    SchedulesPeriodViewRead,
    ScheduleWorkingAck,
    ScheduleWorkingPut,
    ScheduleWorkingRead,
)
from .user import (
    UserAdminCreate,
    UserAdminList,
    UserAdminRead,
    UserAdminUpdate,
    UserRead,
)

# Explicit public surface for this package
__all__ = [
    # Enums / shared
    "Role",
    "DoctorRole",
    "ShiftType",
    "ScheduleStatus",
    "PreferenceStatus",
    "PeriodStatus",
    "RiskLevel",
    "ErrorPayload",
    # Auth / User
    "LoginRequest",
    "TokenResponse",
    "SetPasswordRequest",
    "SetPasswordResponse",
    "UserRead",
    "UserAdminCreate",
    "UserAdminRead",
    "UserAdminUpdate",
    "UserAdminList",
    # Doctor
    "DoctorCreate",
    "DoctorPut",
    "DoctorRead",
    "DoctorList",
    "DoctorMini",
    # Preferences & Availability
    "PreferenceWorkingPut",
    "PreferenceWorkingRead",
    "PreferenceAutosaveAck",
    "PreferenceCheckpointCreated",
    "PreferenceRevertRead",
    "PreferencesSummaryRead",
    "PreferencesDeadlineRead",
    "PreferencesDeadlinePut",
    "AvailabilityOverviewRead",
    "AvailabilityDayRead",
    # Schedules
    "Assignment",
    "SchedulePayload",
    "IgnoreSlot",
    "ScheduleGenerateRequest",
    "ScheduleGenerateCreated",
    "ScheduleWorkingRead",
    "ScheduleWorkingPut",
    "ScheduleWorkingAck",
    "ScheduleDraftView",
    "SchedulePublishedView",
    "SchedulesPeriodViewRead",
    "ScheduleCheckpointRequest",
    "ScheduleCheckpointCreated",
    "ScheduleRevertRead",
    "SchedulePublishRequest",
    "SchedulePublishCreated",
    "SchedulePublishedRevertRead",
    "SchedulePublishedRead",
    "MyAssignment",
    "MyAssignmentsRead",
    # Diagnostics
    "DiagnosticsRead",
    "DiagnosticsSummary",
    # Export (query DTO; response is a file stream)
    "ScheduleExportQuery",
    # Availability
    "AvailabilityDaySummary",
    "AvailabilityRiskLevel",
]
