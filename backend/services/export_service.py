"""
Export Service — create XLSX/PDF/ICS exports of a doctor's published schedule.

Responsibilities:
- Load schedule and doctor data from the DB.
- Call helper modules in utils/exporters/ to build files.
- Return binary payload with proper metadata (content-type, filename).

Notes:
- This service returns bytes + content-type/filename metadata; routers wrap it into HTTP responses.
- Export MUST use a frozen version resolved via POINTER ('published'),
  NOT the mutable 'working'.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from backend.db.session import SessionLocal
from backend.models.orm.doctor import Doctor
from backend.models.orm.schedule import SchedulePointer, ScheduleVersion
from backend.models.schemas.schedule import SchedulePayload
from backend.services.errors import DomainError
from backend.utils.exporters import DoctorExportData, ExportResult, TeamExportData
from backend.utils.timez import ORG_TZ

_CONTENT_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
    "ics": "text/calendar; charset=utf-8",
}


def _get_builder(fmt: str):
    """Lazy-import builders so third-party libs (openpyxl, reportlab, icalendar)
    are only loaded when an export is actually requested — not at server startup."""
    if fmt == "xlsx":
        from backend.utils.exporters.xlsx_builder import build_xlsx
        return build_xlsx
    if fmt == "pdf":
        from backend.utils.exporters.pdf_builder import build_pdf
        return build_pdf
    if fmt == "ics":
        from backend.utils.exporters.ics_builder import build_ics
        return build_ics
    raise ValueError(f"unknown format: {fmt}")


def _get_team_builder(fmt: str):
    """Lazy-import team builders."""
    if fmt == "xlsx":
        from backend.utils.exporters.xlsx_builder import build_team_xlsx
        return build_team_xlsx
    if fmt == "pdf":
        from backend.utils.exporters.pdf_builder import build_team_pdf
        return build_team_pdf
    if fmt == "ics":
        from backend.utils.exporters.ics_builder import build_team_ics
        return build_team_ics
    raise ValueError(f"unknown team format: {fmt}")


class ExportService:
    """Stateless service: each method opens its own session."""

    def export_my_schedule(
        self,
        year: int,
        month: int,
        *,
        doctor_id: int,
        fmt: Literal["xlsx", "pdf", "ics"],
    ) -> ExportResult:
        """Build an export file for *doctor_id*'s published schedule."""

        with SessionLocal() as session:
            # 1. Resolve published version via pointer
            ptr = session.get(SchedulePointer, {"year": year, "month": month})
            if ptr is None or ptr.current_published_version_id is None:
                raise DomainError(
                    "not_found",
                    context={
                        "where": "export_my_schedule.no_published",
                        "year": year,
                        "month": month,
                    },
                )

            ver = session.get(ScheduleVersion, int(ptr.current_published_version_id))
            if ver is None:
                raise DomainError(
                    "not_found",
                    context={
                        "where": "export_my_schedule.version_missing",
                        "year": year,
                        "month": month,
                        "version_id": int(ptr.current_published_version_id),
                    },
                )

            # 2. Parse payload and filter assignments for this doctor
            payload = SchedulePayload.model_validate(ver.payload)
            my_assignments = [
                {"day": int(a.day), "shift_type": str(a.shift_type.value)}
                for a in (payload.assignments or [])
                if int(a.doctor_id) == int(doctor_id)
            ]
            my_assignments.sort(key=lambda a: (a["day"], a["shift_type"]))

            # 3. Load doctor info
            doctor = session.get(Doctor, doctor_id)
            if doctor is None:
                raise DomainError(
                    "not_found",
                    context={
                        "where": "export_my_schedule.doctor_missing",
                        "doctor_id": doctor_id,
                    },
                )

            # 4. Build export data
            data = DoctorExportData(
                doctor_id=doctor_id,
                first_name=doctor.first_name,
                last_name=doctor.last_name,
                role=doctor.role.value,
                year=year,
                month=month,
                org_timezone=ORG_TZ,
                assignments=my_assignments,
            )

            # 5. Build file
            builder = _get_builder(fmt)
            content = builder(data)

            return ExportResult(
                content=content,
                content_type=_CONTENT_TYPES[fmt],
                filename=f"schedule-{year}-{month:02d}.{fmt}",
            )

    def export_team_schedule(
        self,
        year: int,
        month: int,
        *,
        fmt: Literal["xlsx", "pdf", "ics"],
        doctor_id: int | None = None,
        shift_type: str | None = None,
        role: str | None = None,
    ) -> ExportResult:
        """Build an export file for the team's published schedule.

        Optional filters narrow down the exported assignments:
        - doctor_id: single doctor only
        - shift_type: "onsite" | "oncall"
        - role: "specialist" | "resident"
        """

        with SessionLocal() as session:
            # 1. Resolve published version via pointer
            ptr = session.get(SchedulePointer, {"year": year, "month": month})
            if ptr is None or ptr.current_published_version_id is None:
                raise DomainError(
                    "not_found",
                    context={
                        "where": "export_team_schedule.no_published",
                        "year": year,
                        "month": month,
                    },
                )

            ver = session.get(ScheduleVersion, int(ptr.current_published_version_id))
            if ver is None:
                raise DomainError(
                    "not_found",
                    context={
                        "where": "export_team_schedule.version_missing",
                        "year": year,
                        "month": month,
                        "version_id": int(ptr.current_published_version_id),
                    },
                )

            # 2. Parse payload — all assignments, resolve doctor info
            payload = SchedulePayload.model_validate(ver.payload)

            all_doctor_ids = {int(a.doctor_id) for a in (payload.assignments or [])}
            doctors_by_id: dict[int, Doctor] = {}
            for did in all_doctor_ids:
                doc = session.get(Doctor, did)
                if doc is not None:
                    doctors_by_id[did] = doc

            # 3. Filter assignments
            team_assignments = []
            for a in payload.assignments or []:
                did = int(a.doctor_id)
                doc = doctors_by_id.get(did)

                # Apply filters
                if doctor_id is not None and did != doctor_id:
                    continue
                if shift_type is not None and a.shift_type.value != shift_type:
                    continue
                if role is not None and doc is not None and doc.role.value != role:
                    continue

                doctor_name = f"Dr. {doc.first_name} {doc.last_name}" if doc else f"Doctor #{did}"
                doctor_last_name = doc.last_name if doc else f"#{did}"
                team_assignments.append({
                    "day": int(a.day),
                    "shift_type": str(a.shift_type.value),
                    "doctor_name": doctor_name,
                    "doctor_last_name": doctor_last_name,
                })

            # 4. Build export data
            data = TeamExportData(
                year=year,
                month=month,
                org_timezone=ORG_TZ,
                assignments=team_assignments,
                shift_type_filter=shift_type,
            )

            # 5. Build file
            builder = _get_team_builder(fmt)
            content = builder(data)

            return ExportResult(
                content=content,
                content_type=_CONTENT_TYPES[fmt],
                filename=f"team-schedule-{year}-{month:02d}.{fmt}",
            )

    # ---- Calendar feed (subscription) methods ----

    def get_or_create_calendar_token(self, doctor_id: int) -> str:
        """Return the doctor's calendar feed token, creating one if needed."""
        with SessionLocal() as session:
            doctor = session.get(Doctor, doctor_id)
            if doctor is None:
                raise DomainError(
                    "not_found",
                    context={"where": "calendar_token.doctor_missing", "doctor_id": doctor_id},
                )
            if doctor.calendar_feed_token is None:
                doctor.calendar_feed_token = str(uuid.uuid4())
                session.commit()
            return str(doctor.calendar_feed_token)

    def regenerate_calendar_token(self, doctor_id: int) -> str:
        """Overwrite the doctor's feed token with a new UUID (old URLs become 404)."""
        with SessionLocal() as session:
            doctor = session.get(Doctor, doctor_id)
            if doctor is None:
                raise DomainError(
                    "not_found",
                    context={"where": "calendar_token.doctor_missing", "doctor_id": doctor_id},
                )
            doctor.calendar_feed_token = str(uuid.uuid4())
            session.commit()
            return str(doctor.calendar_feed_token)

    def build_calendar_feed(self, token: str) -> bytes:
        """Build an ICS feed for the doctor identified by *token*.

        Includes current month + next month published assignments.
        Raises DomainError("not_found") if token is invalid or doctor inactive.
        """
        from backend.utils.exporters.ics_builder import build_feed_ics

        with SessionLocal() as session:
            # 1. Lookup doctor by token
            doctor = (
                session.query(Doctor)
                .filter(Doctor.calendar_feed_token == token, Doctor.is_active == True)  # noqa: E712
                .first()
            )
            if doctor is None:
                raise DomainError(
                    "not_found",
                    context={"where": "calendar_feed.invalid_token"},
                )

            # 2. Determine prev + current + next month
            now = datetime.now(ZoneInfo(ORG_TZ))
            prev_m, prev_y = (12, now.year - 1) if now.month == 1 else (now.month - 1, now.year)
            next_m, next_y = (1, now.year + 1) if now.month == 12 else (now.month + 1, now.year)
            periods = [(prev_y, prev_m), (now.year, now.month), (next_y, next_m)]

            # 3. Gather assignments from published schedules
            all_assignments: list[dict] = []
            for y, m in periods:
                ptr = session.get(SchedulePointer, {"year": y, "month": m})
                if ptr is None or ptr.current_published_version_id is None:
                    continue
                ver = session.get(ScheduleVersion, int(ptr.current_published_version_id))
                if ver is None:
                    continue
                payload = SchedulePayload.model_validate(ver.payload)
                for a in payload.assignments or []:
                    if int(a.doctor_id) == doctor.id:
                        all_assignments.append({
                            "year": y,
                            "month": m,
                            "day": int(a.day),
                            "shift_type": str(a.shift_type.value),
                        })

            # 4. Build ICS
            return build_feed_ics(
                doctor_id=doctor.id,
                first_name=doctor.first_name,
                last_name=doctor.last_name,
                org_timezone=ORG_TZ,
                assignments=all_assignments,
            )

    def build_team_calendar_feed(self, token: str) -> bytes:
        """Build an ICS feed with the full team schedule (current + next month).

        Uses the doctor's token for authorization only — returns ALL assignments.
        Raises DomainError("not_found") if token is invalid or doctor inactive.
        """
        from backend.utils.exporters.ics_builder import build_team_feed_ics

        with SessionLocal() as session:
            # 1. Validate token — any active doctor can access the team feed
            doctor = (
                session.query(Doctor)
                .filter(Doctor.calendar_feed_token == token, Doctor.is_active == True)  # noqa: E712
                .first()
            )
            if doctor is None:
                raise DomainError(
                    "not_found",
                    context={"where": "team_calendar_feed.invalid_token"},
                )

            # 2. Determine prev + current + next month
            now = datetime.now(ZoneInfo(ORG_TZ))
            prev_m, prev_y = (12, now.year - 1) if now.month == 1 else (now.month - 1, now.year)
            next_m, next_y = (1, now.year + 1) if now.month == 12 else (now.month + 1, now.year)
            periods = [(prev_y, prev_m), (now.year, now.month), (next_y, next_m)]

            # 3. Gather ALL assignments from published schedules
            all_doctor_ids: set[int] = set()
            raw_assignments: list[tuple[int, int, int, str, int]] = []  # (y, m, day, shift, doc_id)
            for y, m in periods:
                ptr = session.get(SchedulePointer, {"year": y, "month": m})
                if ptr is None or ptr.current_published_version_id is None:
                    continue
                ver = session.get(ScheduleVersion, int(ptr.current_published_version_id))
                if ver is None:
                    continue
                payload = SchedulePayload.model_validate(ver.payload)
                for a in payload.assignments or []:
                    did = int(a.doctor_id)
                    all_doctor_ids.add(did)
                    raw_assignments.append((y, m, int(a.day), str(a.shift_type.value), did))

            # 4. Resolve doctor names
            doctors_by_id: dict[int, Doctor] = {}
            for did in all_doctor_ids:
                doc = session.get(Doctor, did)
                if doc is not None:
                    doctors_by_id[did] = doc

            # 5. Build assignment dicts with doctor names
            team_assignments: list[dict] = []
            for y, m, day, shift_type, did in raw_assignments:
                doc = doctors_by_id.get(did)
                doctor_name = f"Dr. {doc.first_name} {doc.last_name}" if doc else f"Doctor #{did}"
                team_assignments.append({
                    "year": y,
                    "month": m,
                    "day": day,
                    "shift_type": shift_type,
                    "doctor_name": doctor_name,
                })

            # 6. Build ICS
            return build_team_feed_ics(
                org_timezone=ORG_TZ,
                assignments=team_assignments,
            )
