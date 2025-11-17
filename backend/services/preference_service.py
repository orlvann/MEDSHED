# backend/services/preference_service.py
"""
Preference Service — monthly preference forms.

Handles:
- Receiving and validating doctors' monthly preference forms.
- Ensuring data consistency (e.g., min <= max, no overlapping unavailable/preferred days).
- Storing preferences in the database.

Responsibilities:
- Perform domain validation beyond schema-level checks.
- Normalize/clean inputs (days 1..31, deduplicate/sort).
- Maintain auditability (who changed what and when).

Data model guidance:
- Source of history is *versions store* + *pointer* (per {year, month, doctor_id}).
- 'working' row is ephemeral (for autosave only) and never the history source.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from backend.db.session import SessionLocal
from backend.models.common_enums import DeadlineStatus, PeriodStatus, PreferenceStatus
from backend.models.orm.preference import (
    PreferenceDeadline,
    PreferencePointer,
    PreferenceWorking,
)
from backend.models.schemas import (
    PreferenceAutosaveAck,
    PreferenceCheckpointCreated,
    PreferenceRevertRead,
    PreferencesDeadlinePut,
    PreferencesDeadlineRead,
    PreferencesSummaryRead,
    PreferenceWorkingPut,
    PreferenceWorkingRead,
)
from backend.routers.deps import UserCtx
from backend.utils.timez import ORG_TZ, get_period_status, now_utc

# ------------------------------------------------------------------------------
# Read / Summary
# ------------------------------------------------------------------------------


def get_working(*, year: int, month: int, doctor_id: int, actor: UserCtx) -> PreferenceWorkingRead:
    """
    Read current editable state for a given doctor and period.

    Reads:
    - PreferenceWorking  (current editable form, autosave buffer)
    - PreferencePointer  (hints: submitted status, version_id, submitted_at/by_*)

    If there is no working row:
    - returns "allow all" defaults (meaning: fully available),
    - but still uses pointer hints if a checkpoint exists.
    """
    period_status = PeriodStatus(get_period_status(year, month))

    with SessionLocal() as session:
        # 1) Editable buffer (may or may not exist).
        working: Optional[PreferenceWorking] = (
            session.query(PreferenceWorking).filter_by(doctor_id=doctor_id, year=year, month=month).one_or_none()
        )

        # 2) Pointer with history hints (checkpoint, submitted_at/by_*).
        pointer: Optional[PreferencePointer] = (
            session.query(PreferencePointer).filter_by(doctor_id=doctor_id, year=year, month=month).one_or_none()
        )

    # 3) Derive status from pointer: submitted if there is a checkpoint.
    if pointer and pointer.current_checkpoint_id:
        pref_status = PreferenceStatus.submitted
    else:
        pref_status = PreferenceStatus.missing

    # 4) Map working row (or defaults) to DTO fields.
    if working is not None:
        unavailable_duty_days = working.unavailable_duty_days or []
        unavailable_oncall_days = working.unavailable_oncall_days or []
        preferred_duty_days = working.preferred_duty_days or []
        preferred_oncall_days = working.preferred_oncall_days or []

        min_duties_weekdays = working.min_duties_weekdays
        max_duties_weekdays = working.max_duties_weekdays
        min_duties_weekends = working.min_duties_weekends
        max_duties_weekends = working.max_duties_weekends
        min_oncall_weekdays = working.min_oncall_weekdays
        max_oncall_weekdays = working.max_oncall_weekdays
        min_oncall_weekends = working.min_oncall_weekends
        max_oncall_weekends = working.max_oncall_weekends

        weekend_back_to_back_allowed = working.weekend_back_to_back_allowed
        preferred_partners = working.preferred_partners or []
        comments = working.comments
        last_admin_note = working.last_admin_note
    else:
        # No working row yet → treat as "allow all" defaults.
        unavailable_duty_days = []
        unavailable_oncall_days = []
        preferred_duty_days = []
        preferred_oncall_days = []

        min_duties_weekdays = 0
        max_duties_weekdays = None
        min_duties_weekends = 0
        max_duties_weekends = None
        min_oncall_weekdays = 0
        max_oncall_weekdays = None
        min_oncall_weekends = 0
        max_oncall_weekends = None

        weekend_back_to_back_allowed = True
        preferred_partners = []
        comments = None
        last_admin_note = None

    # 5) Pointer hints (may be None if no checkpoint).
    if pointer is not None:
        version_id = pointer.current_checkpoint_id
        submitted_at = pointer.submitted_at
        submitted_by_role = pointer.submitted_by_role
        submitted_by_user_id = pointer.submitted_by_user_id
    else:
        version_id = None
        submitted_at = None
        submitted_by_role = None
        submitted_by_user_id = None

    # 6) For now, UNDO/REDO flags are always False.
    #    Later we will compute them from PreferenceVersion history.
    can_undo = False
    can_redo = False

    return PreferenceWorkingRead(
        doctor_id=doctor_id,
        year=year,
        month=month,
        unavailable_duty_days=unavailable_duty_days,
        unavailable_oncall_days=unavailable_oncall_days,
        preferred_duty_days=preferred_duty_days,
        preferred_oncall_days=preferred_oncall_days,
        min_duties_weekdays=min_duties_weekdays,
        max_duties_weekdays=max_duties_weekdays,
        min_duties_weekends=min_duties_weekends,
        max_duties_weekends=max_duties_weekends,
        min_oncall_weekdays=min_oncall_weekdays,
        max_oncall_weekdays=max_oncall_weekdays,
        min_oncall_weekends=min_oncall_weekends,
        max_oncall_weekends=max_oncall_weekends,
        weekend_back_to_back_allowed=weekend_back_to_back_allowed,
        preferred_partners=preferred_partners,
        comments=comments,
        status=pref_status,
        version_id=version_id,
        submitted_at=submitted_at,
        submitted_by_role=submitted_by_role,
        submitted_by_user_id=submitted_by_user_id,
        last_admin_note=last_admin_note,
        can_undo=can_undo,
        can_redo=can_redo,
        org_timezone=ORG_TZ,
        period_status=period_status,
    )


def read_summary(*, year: int, month: int, actor: UserCtx) -> PreferencesSummaryRead:
    """
    Aggregated summary view for admin: which doctors submitted preferences vs missing.

    TODO:
    - Aggregate from PreferencePointer (current_checkpoint_id IS NULL / NOT NULL).
    - Set last_update_at based on max(created_at) from PreferenceVersion for this period.
    """
    return PreferencesSummaryRead(
        year=year,
        month=month,
        submitted=[42, 7, 9],
        missing=[11, 13, 21],
        last_update_at=now_utc(),
    )


# ------------------------------------------------------------------------------
# Autosave / Checkpoint
# ------------------------------------------------------------------------------


def save_working_autosave(
    *,
    year: int,
    month: int,
    doctor_id: int,
    payload: PreferenceWorkingPut,
    actor: UserCtx,
) -> PreferenceAutosaveAck:
    """
    Autosave handler.

    Rules:
    - Upsert into PreferenceWorking for (doctor_id, year, month).
    - Do NOT touch PreferenceVersion / PreferencePointer here.
    - Increment lock_version on each save (when wired).
    - Return hints from PreferencePointer (status, version_id, can_undo/can_redo later).
    """
    now = now_utc()

    with SessionLocal() as session:
        # 1) Get or create working row.
        working: Optional[PreferenceWorking] = (
            session.query(PreferenceWorking).filter_by(doctor_id=doctor_id, year=year, month=month).one_or_none()
        )

        if working is None:
            # New working row for this doctor+period.
            working = PreferenceWorking(
                doctor_id=doctor_id,
                year=year,
                month=month,
                # lock_version default=1 from ORM (server_default / default)
            )
            session.add(working)
            # Po session.add(), a lock_version zostawiamy ORM-owi (0→1).
        else:
            # Existing row → optimistic locking later; dziś tylko inkrement.
            current_lv = working.lock_version or 1
            working.lock_version = current_lv + 1

        # 2) Apply editable fields from payload.
        working.unavailable_duty_days = payload.unavailable_duty_days
        working.unavailable_oncall_days = payload.unavailable_oncall_days
        working.preferred_duty_days = payload.preferred_duty_days
        working.preferred_oncall_days = payload.preferred_oncall_days

        working.min_duties_weekdays = payload.min_duties_weekdays
        working.max_duties_weekdays = payload.max_duties_weekdays
        working.min_duties_weekends = payload.min_duties_weekends
        working.max_duties_weekends = payload.max_duties_weekends
        working.min_oncall_weekdays = payload.min_oncall_weekdays
        working.max_oncall_weekdays = payload.max_oncall_weekdays
        working.min_oncall_weekends = payload.min_oncall_weekends
        working.max_oncall_weekends = payload.max_oncall_weekends

        working.weekend_back_to_back_allowed = payload.weekend_back_to_back_allowed
        working.preferred_partners = payload.preferred_partners
        working.comments = payload.comments

        # 3) Audit fields.
        working.last_saved_at = now
        working.last_saved_by_user_id = actor.user_id
        working.last_saved_by_role = actor.role
        # last_admin_note is managed separately (e.g. by admin workflows).

        session.commit()
        session.refresh(working)

        # 4) Pointer hints (status + version_id).
        pointer: Optional[PreferencePointer] = (
            session.query(PreferencePointer).filter_by(doctor_id=doctor_id, year=year, month=month).one_or_none()
        )

        if pointer and pointer.current_checkpoint_id:
            pref_status = PreferenceStatus.submitted
            version_id = pointer.current_checkpoint_id
            # UNDO/REDO flags pozostawiamy na razie False – dopniemy przy wersjach.
            can_undo = False
            can_redo = False
        else:
            pref_status = PreferenceStatus.missing
            version_id = None
            can_undo = False
            can_redo = False

    return PreferenceAutosaveAck(
        doctor_id=doctor_id,
        year=year,
        month=month,
        updated_at=working.last_saved_at or now,
        status=pref_status,
        version_id=version_id,
        can_undo=can_undo,
        can_redo=can_redo,
        lock_version=working.lock_version,
    )


def create_checkpoint(*, year: int, month: int, doctor_id: int, actor: UserCtx) -> PreferenceCheckpointCreated:
    """
    Create a new immutable checkpoint for the current working state.

    TODO:
    - Read PreferenceWorking for (doctor_id, year, month).
    - Insert new PreferenceVersion with JSON payload snapshot.
    - Move PreferencePointer.current_checkpoint_id to the new version.
    - Prune history (keep last N versions).
    """
    now = now_utc()
    return PreferenceCheckpointCreated(
        doctor_id=doctor_id,
        year=year,
        month=month,
        unavailable_duty_days=[7, 14],
        unavailable_oncall_days=[8],
        preferred_duty_days=[10, 11],
        preferred_oncall_days=[12],
        min_duties_weekdays=2,
        max_duties_weekdays=6,
        min_duties_weekends=1,
        max_duties_weekends=2,
        min_oncall_weekdays=2,
        max_oncall_weekdays=4,
        min_oncall_weekends=0,
        max_oncall_weekends=2,
        weekend_back_to_back_allowed=False,
        preferred_partners=[7],
        comments="avoid Mondays",
        status=PreferenceStatus.submitted,
        version_id="prefv_2026_02_doctor11_0001",
        submitted_at=now,
        submitted_by_user_id=actor.user_id,
        submitted_by_role=actor.role,
        can_undo=True,
        can_redo=False,
        processed_at=now,
    )


def revert_last(*, year: int, month: int, doctor_id: int, actor: UserCtx) -> PreferenceRevertRead:
    """
    UNDO: move pointer to previous checkpoint and update working snapshot.

    TODO:
    - Find previous PreferenceVersion for this doctor/period.
    - Move PreferencePointer.current_checkpoint_id backward.
    - Overwrite PreferenceWorking with the payload from that version.
    """
    now = now_utc()
    return PreferenceRevertRead(
        doctor_id=doctor_id,
        year=year,
        month=month,
        unavailable_duty_days=[7, 14],
        unavailable_oncall_days=[8],
        preferred_duty_days=[10, 11],
        preferred_oncall_days=[12],
        min_duties_weekdays=2,
        max_duties_weekdays=6,
        min_duties_weekends=1,
        max_duties_weekends=2,
        min_oncall_weekdays=2,
        max_oncall_weekdays=4,
        min_oncall_weekends=0,
        max_oncall_weekends=2,
        weekend_back_to_back_allowed=False,
        preferred_partners=[7],
        comments="avoid Mondays",
        reverted_at=now,
        version_id="prefv_2026_02_doctor11_0000",
        current_created_by_role=actor.role,
        current_created_by_user_id=actor.user_id,
        current_created_at=now,
        can_undo=True,
        can_redo=True,
    )


def revert_next(*, year: int, month: int, doctor_id: int, actor: UserCtx) -> PreferenceRevertRead:
    """
    REDO: move pointer to next checkpoint and update working snapshot.

    TODO:
    - Find next PreferenceVersion for this doctor/period.
    - Move PreferencePointer.current_checkpoint_id forward.
    - Overwrite PreferenceWorking with the payload from that version.
    """
    now = now_utc()
    return PreferenceRevertRead(
        doctor_id=doctor_id,
        year=year,
        month=month,
        unavailable_duty_days=[7, 14],
        unavailable_oncall_days=[8],
        preferred_duty_days=[10, 11],
        preferred_oncall_days=[12],
        min_duties_weekdays=2,
        max_duties_weekdays=6,
        min_duties_weekends=1,
        max_duties_weekends=2,
        min_oncall_weekdays=2,
        max_oncall_weekdays=4,
        min_oncall_weekends=0,
        max_oncall_weekends=2,
        weekend_back_to_back_allowed=False,
        preferred_partners=[7],
        comments="avoid Mondays",
        reverted_at=now,
        version_id="prefv_2026_02_doctor11_0001",
        current_created_by_role=actor.role,
        current_created_by_user_id=actor.user_id,
        current_created_at=now,
        can_undo=True,
        can_redo=False,
    )


# ------------------------------------------------------------------------------
# Deadlines
# ------------------------------------------------------------------------------


def get_deadline(*, year: int, month: int, actor: UserCtx) -> PreferencesDeadlineRead:
    """
    Read deadline configuration for a period.

    Rules:
    - If there is no PreferenceDeadline row for (year, month):
        * deadline = None
        * status   = DeadlineStatus.open
        * org_timezone = ORG_TZ
    - If there is a row:
        * deadline = stored UTC timestamp (tz-aware)
        * status   = compute_deadline_status(deadline_utc)
        * org_timezone = row.org_timezone
    """
    with SessionLocal() as session:
        row = session.query(PreferenceDeadline).filter_by(year=year, month=month).one_or_none()

        if row is None:
            deadline_utc = None
            org_tz = ORG_TZ
        else:
            deadline_utc = row.deadline_utc
            org_tz = row.org_timezone

    status = compute_deadline_status(deadline_utc=deadline_utc)

    return PreferencesDeadlineRead(
        year=year,
        month=month,
        deadline=deadline_utc,
        status=status,
        org_timezone=org_tz,
    )


def upsert_deadline(*, year: int, month: int, body: dict, actor: UserCtx) -> PreferencesDeadlinePut:
    """
    Create or update deadline for a period.

    Input body shape (example):
        {"deadline": "2026-01-22T23:59:59Z"}

    Rules:
    - Parse ISO string from body["deadline"].
    - If datetime is naive (no tzinfo) -> interpret as ORG_TZ and convert to UTC.
    - If datetime has tzinfo (e.g. "Z" / "+01:00") -> convert to UTC.
    - Upsert PreferenceDeadline row.
    """
    if "deadline" not in body:
        # Simple guard; later you can convert this to a structured error.
        raise ValueError("deadline field is required")

    raw_deadline = body["deadline"]

    # 1) Parse into datetime
    if isinstance(raw_deadline, str):
        # Support common "Z" suffix for UTC
        if raw_deadline.endswith("Z"):
            raw_deadline = raw_deadline.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(raw_deadline)
    elif isinstance(raw_deadline, datetime):
        parsed = raw_deadline
    else:
        raise ValueError("deadline must be ISO string or datetime")

    org_tzinfo = ZoneInfo(ORG_TZ)

    # 2) Interpret / normalize to org timezone
    if parsed.tzinfo is None:
        # Treat naive datetime as ORG_TZ local time.
        local_dt = parsed.replace(tzinfo=org_tzinfo)
    else:
        # Normalize to organization timezone first (optional).
        local_dt = parsed.astimezone(org_tzinfo)

    # 3) Store in UTC in DB (tz-aware)
    deadline_utc = local_dt.astimezone(ZoneInfo("UTC"))

    with SessionLocal() as session:
        row = session.query(PreferenceDeadline).filter_by(year=year, month=month).one_or_none()

        if row is None:
            row = PreferenceDeadline(
                year=year,
                month=month,
                deadline_utc=deadline_utc,
                org_timezone=ORG_TZ,
            )
            session.add(row)
        else:
            row.deadline_utc = deadline_utc
            row.org_timezone = ORG_TZ

        session.commit()
        session.refresh(row)

        status = compute_deadline_status(deadline_utc=row.deadline_utc)

    return PreferencesDeadlinePut(
        year=row.year,
        month=row.month,
        deadline=row.deadline_utc,
        status=status,
        org_timezone=row.org_timezone,
    )


# ------------------------------------------------------------------------------
# Deadline helpers / doctor lock
# ------------------------------------------------------------------------------


def compute_deadline_status(*, deadline_utc: Optional[datetime]) -> DeadlineStatus:
    """
    Helper: convert deadline timestamp to DeadlineStatus.open | DeadlineStatus.locked.

    Rules:
    - If there is no deadline row (deadline_utc is None) → DeadlineStatus.open.
    - If current UTC time is before the deadline → DeadlineStatus.open.
    - Otherwise → DeadlineStatus.locked.

    Note:
    - DB stores deadline_utc as timezone-aware UTC (DateTime(timezone=True)).
      If for some reason we get naive datetime, we treat it as UTC.
    """
    if deadline_utc is None:
        # No deadline defined → forms are open for editing.
        return DeadlineStatus.open

    # Normalize to UTC timezone-aware
    if deadline_utc.tzinfo is None:
        # Defensive: treat naive value as UTC
        deadline_utc = deadline_utc.replace(tzinfo=ZoneInfo("UTC"))
    else:
        deadline_utc = deadline_utc.astimezone(ZoneInfo("UTC"))

    # Compare current UTC with stored UTC deadline.
    return DeadlineStatus.locked if now_utc() >= deadline_utc else DeadlineStatus.open


def is_doctor_locked_for_period(*, year: int, month: int, doctor_id: int) -> bool:
    """
    Return True if the doctor MUST NOT edit preferences for this period.

    Lock rules:
    - History lock:
      If period is 'past' in organization timezone → always locked.
    - Deadline lock (only for doctors, not for admins):
      If deadline exists AND current time is after or equal to deadline_utc → locked.
      If no deadline exists → open (until month becomes 'past').
    """
    # 1) History lock – never allow editing past months at all.
    period_status = get_period_status(year, month)
    if period_status == "past":
        return True

    # 2) Deadline lock – load PreferenceDeadline from DB (if any).
    with SessionLocal() as session:
        row = session.query(PreferenceDeadline).filter_by(year=year, month=month).one_or_none()

        deadline_utc = row.deadline_utc if row is not None else None

    status = compute_deadline_status(deadline_utc=deadline_utc)
    return status == DeadlineStatus.locked
