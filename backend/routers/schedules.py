# backend/routers/schedules.py
# Schedules router — kontrakt MVP:
# - POST  /api/v1/schedules/generate
# - GET   /api/v1/schedules/{year}/{month}                  (period view)
# - GET   /api/v1/schedules/{year}/{month}/working          (read working)
# - PUT   /api/v1/schedules/{year}/{month}/working          (autosave working)
# - POST  /api/v1/schedules/{year}/{month}/checkpoint       (save draft checkpoint + diagnostics)
# - POST  /api/v1/schedules/{year}/{month}/revert-last      (draft UNDO)
# - POST  /api/v1/schedules/{year}/{month}/revert-next      (draft REDO)
# - POST  /api/v1/schedules/{year}/{month}/publish          (publish from working)
# - POST  /api/v1/schedules/{year}/{month}/revert-last-published
# - POST  /api/v1/schedules/{year}/{month}/revert-next-published
# - GET   /api/v1/schedules/{year}/{month}/diagnostics?target=draft|published
# - GET   /api/v1/schedules/export?year=&month=&mode=&format=[&doctor_id=]

from datetime import datetime, timezone

from fastapi import APIRouter, Body, Path, Query, status

from backend.models.schemas import DiagnosticsRead

router = APIRouter(tags=["schedules"])


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 3.4 Schedules (Admin) — Generate
# ---------------------------------------------------------------------------
@router.post(
    "/api/v1/schedules/generate",
    status_code=status.HTTP_201_CREATED,
    summary="Generate schedule: writes working + creates first draft checkpoint",
)
def generate_schedule(
    payload: dict = Body(
        ...,
        description='{"year":2026,"month":2,"participant_doctor_ids":[1,2,5,7],"ignore_days":[],"ignore_slots":[]}',
    ),
):
    # Stub response per contract — replace with scheduling_service.generate(...)
    now = _now_utc()
    year = payload.get("year", 2026)
    month = payload.get("month", 2)
    return {
        "year": year,
        "month": month,
        "status": "draft",
        "working": {
            "participant_doctor_ids": payload.get("participant_doctor_ids", [1, 2, 5, 7]),
            "assignments": [],
            "meta": {"labels": ["as_generated"]},
            "updated_at": now,
        },
        "draft": {
            "version_id": f"schv_{year}_{str(month).zfill(2)}_0001",
            "checkpoints_count": 1,
            "can_undo": False,
            "can_redo": False,
            "payload": {
                "participant_doctor_ids": payload.get("participant_doctor_ids", [1, 2, 5, 7]),
                "assignments": [],
                "meta": {"labels": ["as_generated"], "exceptions": []},
            },
        },
        "diagnostics": {
            "version_id": f"schv_{year}_{str(month).zfill(2)}_0001",
            "computed_at": now,
            "summary": {},  # in real implementation: compute and store cache
        },
    }


# ---------------------------------------------------------------------------
# Schedules Tab — Period View
# ---------------------------------------------------------------------------
@router.get(
    "/api/v1/schedules/{year}/{month}",
    summary="Period view (working + draft pointer + published pointer + diagnostics)",
)
def schedules_period_view(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
):
    now = _now_utc()
    return {
        "year": year,
        "month": month,
        "org_timezone": "Europe/Warsaw",
        "period_status": "current",
        "view": {"default_mode": "draft", "toggle_available": True},
        "working": {
            "exists": True,
            "participant_doctor_ids": [1, 2, 5, 7],
            "assignments": [],
            "meta": {"labels": ["as_generated"]},
            "updated_at": now,
        },
        "draft": {
            "version_id": f"schv_{year}_{str(month).zfill(2)}_0003",
            "checkpoints_count": 3,
            "can_undo": True,
            "can_redo": False,
            "payload": {
                "participant_doctor_ids": [1, 2, 5, 7],
                "assignments": [],
                "meta": {"labels": ["as_generated"], "exceptions": []},
            },
        },
        "published": {
            "version_id": None,
            "publications_count": 0,
            "can_undo": False,
            "can_redo": False,
            "payload": None,
        },
        "diagnostics": {
            "version_id": f"schv_{year}_{str(month).zfill(2)}_0003",
            "computed_at": now,
            "summary": {
                "penalty_total": 42,
                "understaffed_days": 1,
                "rest_violations": 0,
                "fairness_index": 0.92,
                "preference_fulfillment_pct": 86.5,
            },
        },
    }


# ---------------------------------------------------------------------------
# Working — read & autosave
# ---------------------------------------------------------------------------
@router.get(
    "/api/v1/schedules/{year}/{month}/working",
    summary="Read working draft (explicit)",
)
def schedules_working_read(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
):
    return {
        "year": year,
        "month": month,
        "exists": True,
        "participant_doctor_ids": [1, 2, 5, 7],
        "assignments": [],
        "meta": {"labels": ["as_generated"]},
        "updated_at": _now_utc(),
    }


@router.put(
    "/api/v1/schedules/{year}/{month}/working",
    summary="Autosave working (no checkpoint)",
)
def schedules_working_put(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    body: dict = Body(..., description='{"assignments":[...],"meta":{...}}'),
):
    # W realu: update schedule_working + optimistic locking (optional)
    return {"year": year, "month": month, "updated_at": _now_utc()}


# ---------------------------------------------------------------------------
# Save Draft Checkpoint (+diagnostics)
# ---------------------------------------------------------------------------
@router.post(
    "/api/v1/schedules/{year}/{month}/checkpoint",
    status_code=status.HTTP_201_CREATED,
    summary="Create draft checkpoint from working (+diagnostics)",
)
def schedules_checkpoint(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    body: dict = Body(default_factory=dict, description='{"note":"..."}'),
):
    now = _now_utc()
    ver = f"schv_{year}_{str(month).zfill(2)}_0002"
    return {
        "year": year,
        "month": month,
        "draft": {
            "version_id": ver,
            "checkpoints_count": 2,
            "can_undo": True,
            "can_redo": False,
            "payload": {
                "participant_doctor_ids": [1, 2, 5, 7],
                "assignments": [],
                "meta": {"labels": ["as_generated", "touched"], "exceptions": []},
            },
        },
        "diagnostics": {
            "version_id": ver,
            "computed_at": now,
            "summary": {
                "penalty_total": 38,
                "understaffed_days": 0,
                "rest_violations": 0,
                "fairness_index": 0.94,
                "preference_fulfillment_pct": 88.0,
            },
        },
    }


# ---------------------------------------------------------------------------
# Draft UNDO/REDO
# ---------------------------------------------------------------------------
@router.post(
    "/api/v1/schedules/{year}/{month}/revert-last",
    summary="Draft UNDO (pointer move to previous checkpoint + overwrite working)",
)
def schedules_draft_undo(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
):
    now = _now_utc()
    ver = f"schv_{year}_{str(month).zfill(2)}_0001"
    return {
        "year": year,
        "month": month,
        "draft": {
            "version_id": ver,
            "checkpoints_count": 2,
            "can_undo": False,
            "can_redo": True,
            "payload": {
                "participant_doctor_ids": [1, 2, 5, 7],
                "assignments": [],
                "meta": {"labels": ["as_generated"], "exceptions": []},
            },
        },
        "working": {
            "participant_doctor_ids": [1, 2, 5, 7],
            "assignments": [],
            "meta": {"labels": ["as_generated"]},
            "updated_at": now,
        },
        "diagnostics": {
            "version_id": ver,
            "computed_at": now,
            "summary": {
                "penalty_total": 42,
                "understaffed_days": 1,
                "rest_violations": 0,
                "fairness_index": 0.92,
                "preference_fulfillment_pct": 86.5,
            },
        },
    }


@router.post(
    "/api/v1/schedules/{year}/{month}/revert-next",
    summary="Draft REDO (pointer move to next checkpoint + overwrite working)",
)
def schedules_draft_redo(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
):
    now = _now_utc()
    ver = f"schv_{year}_{str(month).zfill(2)}_0002"
    return {
        "year": year,
        "month": month,
        "draft": {
            "version_id": ver,
            "checkpoints_count": 2,
            "can_undo": True,
            "can_redo": False,
            "payload": {
                "participant_doctor_ids": [1, 2, 5, 7],
                "assignments": [],
                "meta": {"labels": ["as_generated", "touched"], "exceptions": []},
            },
        },
        "working": {
            "participant_doctor_ids": [1, 2, 5, 7],
            "assignments": [],
            "meta": {"labels": ["as_generated", "touched"]},
            "updated_at": now,
        },
        "diagnostics": {
            "version_id": ver,
            "computed_at": now,
            "summary": {
                "penalty_total": 38,
                "understaffed_days": 0,
                "rest_violations": 0,
                "fairness_index": 0.94,
                "preference_fulfillment_pct": 88.0,
            },
        },
    }


# ---------------------------------------------------------------------------
# Publish + Published UNDO/REDO
# ---------------------------------------------------------------------------
@router.post(
    "/api/v1/schedules/{year}/{month}/publish",
    status_code=status.HTTP_201_CREATED,
    summary="Publish from working (hard-rule guard; force supported)",
)
def schedules_publish(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    body: dict = Body(..., description='{"force":false,"note":"...", "accepted_exceptions": []}'),
):
    now = _now_utc()
    ver = f"schv_{year}_{str(month).zfill(2)}_0101"
    return {
        "year": year,
        "month": month,
        "published": {
            "version_id": ver,
            "audit": {
                "published_at": now,
                "published_by_user_id": 101,
                "note": body.get("note") or "Finalize",
            },
            "publications_count": 1,
            "can_undo": False,
            "can_redo": False,
            "payload": {
                "participant_doctor_ids": [1, 2, 5, 7],
                "assignments": [],
                "meta": {"labels": ["as_generated", "touched"], "exceptions": []},
            },
        },
    }


@router.post(
    "/api/v1/schedules/{year}/{month}/revert-last-published",
    summary="Published rollback (pointer move to previous published)",
)
def schedules_published_undo(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
):
    ver = f"schv_{year}_{str(month).zfill(2)}_0100"
    return {
        "year": year,
        "month": month,
        "published": {
            "version_id": ver,
            "publications_count": 2,
            "can_undo": False,
            "can_redo": True,
            "payload": {
                "participant_doctor_ids": [1, 2, 5, 7],
                "assignments": [],
                "meta": {"labels": ["as_generated", "touched"], "exceptions": []},
            },
        },
    }


@router.post(
    "/api/v1/schedules/{year}/{month}/revert-next-published",
    summary="Published redo (pointer move to next published)",
)
def schedules_published_redo(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
):
    ver = f"schv_{year}_{str(month).zfill(2)}_0101"
    return {
        "year": year,
        "month": month,
        "published": {
            "version_id": ver,
            "publications_count": 2,
            "can_undo": True,
            "can_redo": False,
            "payload": {
                "participant_doctor_ids": [1, 2, 5, 7],
                "assignments": [],
                "meta": {"labels": ["as_generated", "touched"], "exceptions": []},
            },
        },
    }


# ---------------------------------------------------------------------------
# Diagnostics (fetch)
# ---------------------------------------------------------------------------
@router.get(
    "/api/v1/schedules/{year}/{month}/diagnostics",
    response_model=DiagnosticsRead,
    summary="Diagnostics for draft or published (per pointer)",
)
def schedules_diagnostics(
    year: int = Path(..., ge=1900, le=2100),
    month: int = Path(..., ge=1, le=12),
    target: str = Query(..., pattern="^(draft|published)$"),
):
    # In real implementation: use the pointer for the target,
    # compute if cache missing, persist, and return.
    return {
        "version_id": f"schv_{year}_{str(month).zfill(2)}_0002",
        "computed_at": _now_utc(),
        "summary": {
            "penalty_total": 38,
            "understaffed_days": 0,
            "rest_violations": 0,
            "fairness_index": 0.94,
            "preference_fulfillment_pct": 88.0,
        },
    }


# ---------------------------------------------------------------------------
# Unified Export (binary stream in real implementation)
# ---------------------------------------------------------------------------
@router.get(
    "/api/v1/schedules/export",
    summary="Unified export (draft|published) to xlsx|pdf",
)
def schedules_export(
    year: int = Query(..., ge=1900, le=2100),
    month: int = Query(..., ge=1, le=12),
    mode: str = Query(..., pattern="^(draft|published)$"),
    format: str = Query(..., pattern="^(xlsx|pdf)$"),
    doctor_id: int | None = Query(None, description="Optional for ICS in future; RBAC enforced"),
):
    # Real implementation: StreamingResponse + Content-Disposition with correct filename
    return {
        "detail": "stub: export stream here",
        "year": year,
        "month": month,
        "mode": mode,
        "format": format,
        "doctor_id": doctor_id,
    }
