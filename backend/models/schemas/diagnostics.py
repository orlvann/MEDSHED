from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# ---- Small typed DTOs to avoid raw Dict[Any, Any] ----


class RestRuleFlag(BaseModel):
    day: int = Field(..., ge=1, le=31)
    doctor_id: int
    type: str  # e.g., "insufficient_rest" | "back_to_back_weekend"


class CoverageReport(BaseModel):
    understaffed_days: List[int] = Field(default_factory=list)
    overstaffed_days: List[int] = Field(default_factory=list)
    resident_only_days: List[int] = Field(default_factory=list)
    rest_rule_flags: List[RestRuleFlag] = Field(default_factory=list)
    hotspots: List[int] = Field(default_factory=list)


class PerDoctorStats(BaseModel):
    doctor_id: int
    duties_total: int
    oncall_total: int
    weekends_worked: int
    unavailable_violations: int
    preferences_fulfilled: int
    duty_requested: Optional[int] = None
    oncall_requested: Optional[int] = None


class PreferencesBreakdown(BaseModel):
    fulfilled: int
    unfulfilled: int
    per_doctor: List[PerDoctorStats] = Field(default_factory=list)


class WorkloadDistributionEntry(BaseModel):
    doctor_id: int
    duties: int
    oncall: int


class FairnessBreakdown(BaseModel):
    specialists_avg_duties: float
    residents_avg_duties: float
    distribution: List[WorkloadDistributionEntry] = Field(default_factory=list)


class MissedPair(BaseModel):
    day: int
    pair: List[int]  # [docA, docB]


class PartneringBreakdown(BaseModel):
    preferred_pairs_respected: int
    missed_pairs: List[MissedPair] = Field(default_factory=list)


class DiagnosticsSummary(BaseModel):
    primary_cost: float | int
    secondary_cost: float | int
    penalty_total: float | int
    fairness_gini: float


class DiagnosticsVisuals(BaseModel):
    daily_cost_heatmap: List[int] = Field(default_factory=list)
    violations_timeline: List[Dict[str, int]] = Field(
        default_factory=list
    )  # e.g., {"day": 12, "count": 2}


class DiagnosticsRead(BaseModel):
    schedule_id: int
    summary: DiagnosticsSummary
    coverage: CoverageReport
    preferences: PreferencesBreakdown
    fairness: FairnessBreakdown
    partnering: PartneringBreakdown
    visuals: Optional[DiagnosticsVisuals] = None
    suggestions: Optional[List[Dict[str, Any]]] = None
    exports: Optional[Dict[str, str]] = None  # e.g. {"xlsx_link": "..."}
