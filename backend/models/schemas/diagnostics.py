# backend/models/schemas/diagnostics.py
# -----------------------------------------------------------------------------
# Diagnostics DTO — kept small and stable (leaf module, no back-imports).
#
# MVP contract shape (example):
# {
#   "version_id": "schv_2026_02_0002",
#   "computed_at": "2026-02-01T11:06:00Z",
#   "summary": {
#     "penalty_total": 38,
#     "understaffed_days": 0,
#     "rest_violations": 0,
#     "fairness_index": 0.94,
#     "preference_fulfillment_pct": 88.0
#   },
#   "details": { ... }  // optional
# }
#
# Why this file is a "leaf":
# - It does NOT import schedule schemas (or other app schemas), so others can
#   safely import DiagnosticsRead without creating circular imports.
# -----------------------------------------------------------------------------

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class DiagnosticsSummary(BaseModel):
    """Compact KPIs for a single schedule version (draft checkpoint or published).
    Defaults are safe so the server can always return a minimal payload.
    """

    penalty_total: int = Field(
        0,
        description="Total optimization penalty (lower is better). Aggregated objective or proxy.",
    )
    understaffed_days: int = Field(
        0,
        description="Number of days with missing required assignments.",
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


class DiagnosticsRead(BaseModel):
    """
    Diagnostics payload bound to a concrete schedule version.
    Returned by: GET /api/v1/schedules/{y}/{m}/diagnostics?target=draft|published
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
    summary: DiagnosticsSummary = Field(
        default_factory=lambda: DiagnosticsSummary(),
        description="Compact KPIs for quick UI consumption.",
    )
    # Keep 'details' flexible in MVP. Post-MVP we may replace with a strong type (see below).
    details: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional rich breakdown (JSON). Absent in MVP or when not computed.",
    )


__all__ = [
    "DiagnosticsSummary",
    "DiagnosticsRead",
]


# -----------------------------------------------------------------------------
# POST-MVP (commented ideas to grow the contract safely)
# -----------------------------------------------------------------------------
#
# 1) Strongly-typed `details` instead of a free Dict:
#
# from pydantic import BaseModel, Field
#
# class RestRuleFlag(BaseModel):
#     day: int  # 1..31
#     doctor_id: int
#     type: str  # e.g., "insufficient_rest" | "back_to_back_weekend"
#
# class CoverageReport(BaseModel):
#     understaffed_days: list[int] = []
#     overstaffed_days: list[int] = []
#     resident_only_days: list[int] = []
#     rest_rule_flags: list[RestRuleFlag] = []
#     hotspots: list[int] = []
#
# class PerDoctorStats(BaseModel):
#     doctor_id: int
#     duties_total: int
#     oncall_total: int
#     weekends_worked: int
#     unavailable_violations: int
#     preferences_fulfilled: int
#     duty_requested: int | None = None
#     oncall_requested: int | None = None
#
# class PreferencesBreakdown(BaseModel):
#     fulfilled: int
#     unfulfilled: int
#     per_doctor: list[PerDoctorStats] = []
#
# class WorkloadDistributionEntry(BaseModel):
#     doctor_id: int
#     duties: int
#     oncall: int
#
# class FairnessBreakdown(BaseModel):
#     specialists_avg_duties: float
#     residents_avg_duties: float
#     distribution: list[WorkloadDistributionEntry] = []
#
# class MissedPair(BaseModel):
#     day: int
#     pair: list[int]  # [docA, docB]
#
# class PartneringBreakdown(BaseModel):
#     preferred_pairs_respected: int
#     missed_pairs: list[MissedPair] = []
#
# class DiagnosticsVisuals(BaseModel):
#     daily_cost_heatmap: list[int] = []
#     violations_timeline: list[dict[str, int]] = []  # {"day": 12, "count": 2}
#
# class Suggestion(BaseModel):
#     # e.g., "Swap Dr. 5 and Dr. 7 on day 12 to reduce penalty by 3"
#     message: str
#     impact_penalty_delta: float | int | None = None
#     affected_days: list[int] = []
#     affected_doctors: list[int] = []
#
# class DiagnosticsDetails(BaseModel):
#     coverage: CoverageReport
#     preferences: PreferencesBreakdown
#     fairness: FairnessBreakdown
#     partnering: PartneringBreakdown
#     visuals: DiagnosticsVisuals | None = None
#     suggestions: list[Suggestion] | None = None
#
# # And then replace in DiagnosticsRead (breaking change, plan a minor API bump):
# # details: Optional[DiagnosticsDetails] = None
