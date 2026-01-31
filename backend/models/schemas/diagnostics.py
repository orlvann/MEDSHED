# backend/models/schemas/diagnostics.py
# -----------------------------------------------------------------------------
# Diagnostics DTO — kept small and stable (leaf module, no back-imports).
#
# Why this file is a "leaf":
# - It does NOT import schedule schemas (or other app schemas), so others can
#   safely import DiagnosticsRead without creating circular imports.
#
# NOTE (contract):
# - The API returns a stable typed `details` structure (findings/per_doctor/rankings/audit/components).
# - We may still compute extra debug fields in core, and we keep them inside the typed model
#   as a free dict (components) to avoid losing useful diagnostics.
# -----------------------------------------------------------------------------

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ------------------------------ Summary (KPIs) ------------------------------


class DiagnosticsSummaryRead(BaseModel):
    """Compact KPIs for a single schedule version (working/draft/published).

    Backward compatibility:
    - Older payloads may still send legacy fields.
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

    # OLD (deprecated) fields intentionally removed from the public DTO.
    # They may exist in legacy internal payloads, but they are not part of the API contract.


def _make_diag_summary() -> "DiagnosticsSummaryRead":
    # Provide explicit defaults to satisfy static type checker (Pylance),
    # even though Pydantic would accept a no-arg constructor.
    return DiagnosticsSummaryRead(
        coverage_missing_required_slots=0,
        hard_issues_count=0,
        rest_violations=0,
        fairness_index=1.0,
        preference_fulfillment_pct=100.0,
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
            "Optional per-doctor score used by rankings (higher=better or lower=better depending on convention)."
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


AuditKind = Literal[
    "generation_ignore",
    "publish_acceptance",
    "head_commitment_resolution",
]


class DiagnosticsAuditItemRead(BaseModel):
    """
    One audit row extracted from payload.meta.exceptions.

    What "audit" means here:
    - It is a history of human decisions and accepted exceptions.
    - This includes BOTH:
      * generation-time ignore decisions (slot-level markers),
      * force-publish acceptances (with justification/accepted_at/by),
      * head commitment resolutions (when multiple heads wanted the same slot).
    """

    # Helps FE decide where/how to render the row (tabs/sections/icons),
    # without needing to infer it from the code string.
    kind: Optional[AuditKind] = Field(
        default=None,
        description=(
            "Audit category for UI grouping. "
            "Examples: 'generation_ignore', 'publish_acceptance', 'head_commitment_resolution'."
        ),
    )

    code: str = Field(..., description="Stable exception code accepted by user/admin.")

    # Slot context (used for slot-level exceptions like coverage_ignored_slot).
    # Optional to keep DTO flexible for different exception types.
    day: Optional[int] = Field(
        default=None,
        description="Day number (1..31) if this audit entry refers to a concrete day (e.g., ignored slot).",
    )
    shift_type: Optional[str] = Field(
        default=None,
        description="Shift type string (e.g., 'onsite'/'oncall') if this audit entry refers to a slot.",
    )

    # Human acceptance context (mostly used for publish-time acceptances).
    justification: Optional[str] = Field(
        default=None,
        description="Human justification provided when accepting the exception (if any).",
    )
    accepted_by_user_id: Optional[int] = Field(
        default=None,
        description="User id who accepted the exception (if known).",
    )
    accepted_at: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp when the exception was accepted (if known).",
    )


class DiagnosticsDetailsRead(BaseModel):
    findings: list[DiagnosticsFindingRead] = Field(default_factory=list)
    per_doctor: list[DoctorDiagnosticsRead] = Field(default_factory=list)
    rankings: RankingsRead = Field(default_factory=RankingsRead)

    # Decision history (generation ignores, publish acceptances, etc.).
    # It is extracted from payload.meta.exceptions to keep FE compatible:
    # - payload.meta.exceptions stays unchanged,
    # - diagnostics returns this separate projection for UI display.
    audit: list[DiagnosticsAuditItemRead] = Field(
        default_factory=list,
        description="Audit decision history extracted from payload.meta.exceptions.",
    )

    # Optional debug breakdown from core (safe free-form dict).
    # Example keys depend on the core diagnostics implementation (scoring components, penalties, etc.).
    components: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional debug breakdown of scoring components (free-form JSON).",
    )

    # This field is only used when diagnostics target="working".
    # It helps the UI detect whether diagnostics were computed for the latest
    # working buffer version without needing an extra /working call.
    #
    # NOTE:
    # - For draft/published it should be None.
    # - For working it should be an int (OCC lock version).
    working_lock_version: Optional[int] = Field(
        default=None,
        description="OCC lock version used only for target=working diagnostics.",
    )


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

    details: Optional[DiagnosticsDetailsRead] = Field(
        default=None,
        description="Typed diagnostics breakdown for UI (findings, per-doctor, rankings, audit, components).",
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
    "DiagnosticsAuditItemRead",
    "AuditKind",
]
