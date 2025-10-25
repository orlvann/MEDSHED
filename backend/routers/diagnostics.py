# backend/routers/diagnostics.py
# MVP: diagnostics are fetched per version pointer (draft|published) for a given {year, month}.
# Shape matches DiagnosticsRead from schemas: {version_id, computed_at, summary{...}, details?}

from datetime import datetime, timezone

from fastapi import APIRouter, Path, Query

from backend.models.schemas import DiagnosticsRead

router = APIRouter(tags=["diagnostics"])


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


@router.get(
    "/api/v1/schedules/{year}/{month}/diagnostics",
    response_model=DiagnosticsRead,
    summary="Diagnostics for draft or published (per pointer)",
)
def diagnostics_for_period(
    year: int = Path(..., ge=1900, le=2100, description="Calendar year"),
    month: int = Path(..., ge=1, le=12, description="Month 1..12"),
    target: str = Query(..., pattern="^(draft|published)$", description="Which pointer to use"),
):
    """
    MVP stub:
    - Use the selected pointer (draft|published) for {year,month},
    - If cache for that version_id is missing, compute, persist, and return (real implementation).
    """
    version_suffix = "0002" if target == "draft" else "0101"
    version_id = f"schv_{year}_{str(month).zfill(2)}_{version_suffix}"

    return {
        "version_id": version_id,
        "computed_at": _now_utc(),
        "summary": {
            "penalty_total": 38,
            "understaffed_days": 0,
            "rest_violations": 0,
            "fairness_index": 0.94,
            "preference_fulfillment_pct": 88.0,
        },
        # Optional details (None in MVP; see post-MVP ideas below)
        "details": None,
    }


# -----------------------------------------------------------------------------
# POST-MVP (commented roadmap, mirroring schemas' comments)
# -----------------------------------------------------------------------------
# Possible extensions after MVP:
#
# 1) Enrich `details` with strongly-typed breakdowns:
#    - coverage (under/overstaffed days, rest-rule flags, hotspots),
#    - preferences (fulfilled/unfulfilled, per-doctor stats),
#    - fairness (average duties per role, distribution),
#    - partnering (preferred pairs respected/missed),
#    - visuals (daily cost heatmap, violations timeline),
#    - suggestions (auto-fixes with estimated impact).
#
# 2) Optional new endpoints:
#    - GET  /api/v1/schedules/{year}/{month}/diagnostics/details?target=...
#      (lazy-load heavy details separately to keep the main call light)
#    - POST /api/v1/schedules/{year}/{month}/diagnostics/recompute?target=...
#      (force recomputation & cache refresh for a version)
#
# 3) Streaming/exports:
#    - Provide links in details (e.g., CSV/JSON dumps, plots) when needed.
#
# All of the above should preserve the MVP shape and be additive (non-breaking).
