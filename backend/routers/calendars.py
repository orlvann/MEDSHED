# backend/routers/calendars.py
"""Public calendar feed endpoint — no authentication required.

The UUID token in the URL acts as authorization.
Calendar apps (Google Calendar, Apple Calendar) poll this URL to keep events updated.
"""

from io import BytesIO

from fastapi import APIRouter, Path
from fastapi.responses import StreamingResponse
from starlette import status

from backend.services.export_service import ExportService

router = APIRouter(tags=["calendars"])

_export_svc = ExportService()


@router.get(
    "/api/v1/calendars/{token}.ics",
    summary="Public ICS calendar feed (subscription URL)",
    description=(
        "Returns an ICS calendar for the doctor identified by the UUID token. "
        "No authentication required — the token IS the authorization. "
        "Calendar apps poll this URL to auto-update events."
    ),
    responses={
        200: {
            "description": "ICS calendar file.",
            "content": {"text/calendar": {}},
        },
        404: {"description": "Invalid token or inactive doctor."},
    },
)
def calendar_feed(
    token: str = Path(..., min_length=36, max_length=36),
):
    try:
        ics_bytes = _export_svc.build_calendar_feed(token)
    except ValueError:
        from fastapi import HTTPException

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    return StreamingResponse(
        BytesIO(ics_bytes),
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": "inline",
            "Cache-Control": "no-cache",
        },
    )


@router.get(
    "/api/v1/calendars/{token}/team.ics",
    summary="Public ICS team calendar feed (subscription URL)",
    description=(
        "Returns an ICS calendar with the full team schedule for current + next month. "
        "The doctor's UUID token authorizes access. No filters applied."
    ),
    responses={
        200: {
            "description": "ICS calendar file (full team).",
            "content": {"text/calendar": {}},
        },
        404: {"description": "Invalid token or inactive doctor."},
    },
)
def team_calendar_feed(
    token: str = Path(..., min_length=36, max_length=36),
):
    try:
        ics_bytes = _export_svc.build_team_calendar_feed(token)
    except ValueError:
        from fastapi import HTTPException

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    return StreamingResponse(
        BytesIO(ics_bytes),
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": "inline",
            "Cache-Control": "no-cache",
        },
    )
