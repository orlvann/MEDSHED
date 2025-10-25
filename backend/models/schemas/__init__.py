"""Pydantic DTOs + enums (request/response shapes).
Validate input early; serialize output consistently; power OpenAPI docs."""

# backend/models/schemas/__init__.py
# Public re-exports of Pydantic DTOs for short imports across the codebase.
# Linters: names listed in __all__ are considered intentional exports.

from .auth import LoginRequest, TokenResponse
from .common import (
    DoctorRole,
    ErrorPayload,
    PeriodStatus,
    PreferenceStatus,
    RiskLevel,
    Role,
    ScheduleStatus,
    ShiftType,
)
from .diagnostics import DiagnosticsRead, DiagnosticsSummary
from .doctor import DoctorCreate, DoctorList, DoctorMini, DoctorPut, DoctorRead
from .export import ScheduleExportQuery
from .preference import (
    AvailabilityDayRead,
    AvailabilityOverviewRead,
    PreferenceAutosaveAck,
    PreferenceCheckpointCreated,
    PreferenceRevertRead,
    PreferencesDeadlinePut,
    PreferencesDeadlineRead,
    PreferencesSummaryRead,
    PreferenceWorkingPut,
    PreferenceWorkingRead,
)
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
    ScheduleWorkingPut,
    ScheduleWorkingRead,
)
from .user import UserRead

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
    "UserRead",
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
]
