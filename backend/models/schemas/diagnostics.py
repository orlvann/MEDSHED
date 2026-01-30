# backend/models/schemas/diagnostics.py
# -----------------------------------------------------------------------------
# Diagnostics DTO — kept small and stable (leaf module, no back-imports).
#
# Why this file is a "leaf":
# - It does NOT import schedule schemas (or other app schemas), so others can
#   safely import DiagnosticsRead without creating circular imports.
#
# NOTE (contract evolution):
# - We keep backward compatibility with older payload fields (penalty_total, understaffed_days,
#   and details as a free JSON dict).
# - New typed "Read" models are added to provide a stable contract for FE.
# -----------------------------------------------------------------------------

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ------------------------------ Summary (KPIs) ------------------------------


class DiagnosticsSummaryRead(BaseModel):
    """Compact KPIs for a single schedule version (working/draft/published).

    Backward compatibility:
    - Older payloads may still send `penalty_total` and `understaffed_days`.
    - New contract uses `coverage_missing_required_slots` and `hard_issues_count`.
    - All fields have safe defaults so the server can always return a minimal payload.
    """

    # NEW (stable contract)
    coverage_missing_required_slots: int = Field(
        0,
        description="Number of missing required coverage slots (counted per slot, not per day).",
    )
    hard_issues_count: int = Field(
        0,
        description="Count of hard rule violations (critical issues). Used to block publish when force=false.",
    )
    rest_violations: int = Field(
        0,
        description="Count of hard rest-rule violations detected.",
    )
    fairness_index: float = Field(
        1.0,
        description="Fairness score in [0..1]. 1.0 = perfectly even workload.",
    )
    preference_fulfillment_pct: float = Field(
        100.0,
        description="Satisfied preferences in percent (0..100).",
    )

    # # OLD (deprecated in API; kept for compatibility with current service payload)
    # penalty_total: int = Field(
    #     0,
    #     description="DEPRECATED: Total optimization penalty (lower is better).",
    # )
    # understaffed_days: int = Field(
    #     0,
    #     description="DEPRECATED: Number of days with missing required assignments.",
    # )


def _make_diag_summary() -> "DiagnosticsSummaryRead":
    # Provide explicit defaults to satisfy static type checker (Pylance),
    # even though Pydantic would accept a no-arg constructor.
    return DiagnosticsSummaryRead(
        coverage_missing_required_slots=0,
        hard_issues_count=0,
        rest_violations=0,
        fairness_index=1.0,
        preference_fulfillment_pct=100.0,
        # penalty_total=0,
        # understaffed_days=0,
    )


# Backward-compatible name (some code may still import DiagnosticsSummary).
# Keep it as a real class name for easier runtime/debugging.
class DiagnosticsSummary(DiagnosticsSummaryRead):
    """Backward-compatible alias for older imports."""


# ------------------------------ Findings (stable codes for FE) ------------------------------


DiagnosticsSeverity = Literal["critical", "warning", "info"]


class DiagnosticsFindingRead(BaseModel):
    code: str = Field(..., description="Stable finding code for FE mapping (code -> message).")
    severity: DiagnosticsSeverity = Field(..., description="Finding severity level.")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Small, flexible context payload for the finding (FE may use it for details).",
    )


# ------------------------------ Per-doctor breakdown ------------------------------


class DoctorDiagnosticsRead(BaseModel):
    doctor_id: int
    display_name: str

    assigned_onsite_total: int = 0
    assigned_oncall_total: int = 0

    rest_violations: int = 0

    preference_fulfillment_pct: float = Field(
        100.0,
        description="Satisfied preferences for this doctor in percent (0..100).",
    )
    preferred_days_missed: int = Field(
        0,
        description="How many preferred concrete days were missed (soft objective signal).",
    )

    # Optional score if rankings need it; keep optional to avoid forcing it everywhere.
    score: Optional[float] = Field(
        default=None,
        description=(
            "Optional per-doctor score used by rankings " "(higher=better or lower=better depending on convention)."
        ),
    )


class DoctorRankingItemRead(BaseModel):
    doctor_id: int
    score: float
    reasons_codes: list[str] = Field(
        default_factory=list,
        description="Stable reason codes explaining why the doctor is in this ranking list.",
    )


class RankingsRead(BaseModel):
    top_unhappy: list[DoctorRankingItemRead] = Field(default_factory=list)
    top_happy: list[DoctorRankingItemRead] = Field(default_factory=list)


# ------------------------------ Details envelope ------------------------------


class DiagnosticsDetailsRead(BaseModel):
    findings: list[DiagnosticsFindingRead] = Field(default_factory=list)
    per_doctor: list[DoctorDiagnosticsRead] = Field(default_factory=list)
    rankings: RankingsRead = Field(default_factory=RankingsRead)

    # NOTE:
    # - Field always exists in this DTO.
    # - For draft/published it should be None.
    # - For working it should be an int (OCC lock version).
    working_lock_version: Optional[int] = None


# ------------------------------ Root payload ------------------------------


class DiagnosticsRead(BaseModel):
    """
    Diagnostics payload bound to a schedule target.

    Returned by:
    - GET /api/v1/schedules/{y}/{m}/diagnostics?target=working|draft|published
    - Embedded in Period View and Generate/Checkpoint responses.
    """

    version_id: str = Field(
        ...,
        description="Version identifier (draft checkpoint or published) the diagnostics refer to.",
    )
    computed_at: datetime = Field(
        ...,
        description="UTC timestamp when diagnostics were computed/refreshed (server-side UTC).",
    )

    # NOTE: default_factory must be a zero-arg callable for Pydantic v2 & type checkers.
    summary: DiagnosticsSummaryRead = Field(
        default_factory=_make_diag_summary,
        description="Compact KPIs for quick UI consumption.",
    )

    # Backward compatibility:
    # - Keep the legacy free JSON dict in `details` so existing services/tests won't break.
    # - New typed contract can be filled later in `details_typed` (no behavior change now).
    details: Optional[dict[str, Any]] = Field(
        default=None,
        description="LEGACY: Optional rich breakdown (free JSON dict).",
    )

    details_typed: Optional[DiagnosticsDetailsRead] = Field(
        default=None,
        description="New typed details contract (optional until services start populating it).",
    )


__all__ = [
    "DiagnosticsSeverity",
    "DiagnosticsFindingRead",
    "DoctorDiagnosticsRead",
    "DoctorRankingItemRead",
    "RankingsRead",
    "DiagnosticsSummaryRead",
    "DiagnosticsDetailsRead",
    "DiagnosticsSummary",
    "DiagnosticsRead",
]
