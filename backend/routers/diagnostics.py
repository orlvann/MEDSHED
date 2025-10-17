from fastapi import APIRouter, Path

from backend.models.schemas import (
    DiagnosticsRead,
)

router = APIRouter(tags=["diagnostics"])


@router.get(
    "/api/v1/schedules/{sid}/diagnostics",
    response_model=DiagnosticsRead,
    summary="Diagnostics for schedule",
)
def diagnostics(sid: int = Path(..., ge=1)):
    # TODO: diagnostics_service.get_report(sid)
    return {
        "schedule_id": sid,
        "summary": {
            "primary_cost": 12,
            "secondary_cost": 3,
            "penalty_total": 2,
            "fairness_gini": 0.12,
        },
        "coverage": {
            "understaffed_days": [12],
            "overstaffed_days": [],
            "resident_only_days": [],
            "rest_rule_flags": [{"day": 15, "doctor_id": 7, "type": "insufficient_rest"}],
            "hotspots": [7, 15],
        },
        "preferences": {
            "fulfilled": 20,
            "unfulfilled": 3,
            "per_doctor": [],
        },
        "fairness": {
            "specialists_avg_duties": 5.2,
            "residents_avg_duties": 4.7,
            "distribution": [],
        },
        "partnering": {
            "preferred_pairs_respected": 8,
            "missed_pairs": [],
        },
        "visuals": {
            "daily_cost_heatmap": [0, 1, 2],
            "violations_timeline": [{"day": 12, "count": 2}],
        },
        "suggestions": None,
        "exports": {"xlsx_link": f"/api/v1/schedules/{sid}/export.xlsx"},
    }
