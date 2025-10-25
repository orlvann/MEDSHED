from datetime import datetime
from typing import Dict, Optional

from pydantic import BaseModel

# MVP contract shape:
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


class DiagnosticsSummary(BaseModel):
    penalty_total: int
    understaffed_days: int
    rest_violations: int
    fairness_index: float
    preference_fulfillment_pct: float


class DiagnosticsRead(BaseModel):
    version_id: str
    computed_at: datetime
    summary: DiagnosticsSummary
    details: Optional[Dict] = None  # place richer breakdowns here if you have them


# -----------------------------------------------------------------------------
# POST-MVP (commented ideas to grow the contract safely)
# -----------------------------------------------------------------------------
#
# 1) Strongly-typed `details` instead of a free Dict:
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
