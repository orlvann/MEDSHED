# backend/models/schemas/__init__.py
# Public re-exports of Pydantic DTOs for short imports across the codebase.
# Linters: names listed in __all__ are considered intentional exports.

from .common import DoctorRole, ErrorPayload, PreferenceStatus, Role, ScheduleStatus, ShiftType
from .diagnostics import (
    CoverageReport,
    DiagnosticsRead,
    DiagnosticsSummary,
    DiagnosticsVisuals,
    FairnessBreakdown,
    MissedPair,
    PartneringBreakdown,
    PerDoctorStats,
    PreferencesBreakdown,
    RestRuleFlag,
    WorkloadDistributionEntry,
)
from .doctor import DoctorCreate, DoctorList, DoctorRead, DoctorUpdate
from .export import ExportOptions, ExportResponse
from .preference import (
    PreferenceAuditEntryRead,
    PreferenceCreate,
    PreferenceRead,
    PreferenceSummary,
    PreferenceUpdate,
)
from .schedule import (
    AssignmentRead,
    GenerateScheduleRequest,
    ManualEditRequest,
    PublishRequest,
    ScheduleHistoryItem,
    ScheduleHistoryList,
    ScheduleRead,
)
from .user import LoginRequest, TokenResponse, UserRead

# Explicit public surface for this package
__all__ = [
    "Role",
    "DoctorRole",
    "ShiftType",
    "ScheduleStatus",
    "LoginRequest",
    "TokenResponse",
    "UserRead",
    "DoctorCreate",
    "DoctorUpdate",
    "DoctorRead",
    "DoctorList",
    "PreferenceCreate",
    "PreferenceUpdate",
    "PreferenceRead",
    "PreferenceSummary",
    "AssignmentRead",
    "GenerateScheduleRequest",
    "ManualEditRequest",
    "PublishRequest",
    "ScheduleRead",
    "RestRuleFlag",
    "CoverageReport",
    "PerDoctorStats",
    "DiagnosticsSummary",
    "DiagnosticsVisuals",
    "DiagnosticsRead",
    "ExportOptions",
    "ExportResponse",
    "PreferenceAuditEntryRead",
    "PreferenceStatus",
    "ScheduleHistoryItem",
    "ScheduleHistoryList",
    "ErrorPayload",
    "FairnessBreakdown",
    "MissedPair",
    "PartneringBreakdown",
    "PreferencesBreakdown",
    "WorkloadDistributionEntry",
]
