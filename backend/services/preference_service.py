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

Stubs below mirror the router contract and keep ORM unaffected for now.
Replace bodies with real DB/ORM calls.
"""

from __future__ import annotations

from backend.models.common_enums import PeriodStatus, PreferenceStatus
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

# ------------------------- Read / Summary ----------------------------------


def get_working(*, year: int, month: int, doctor_id: int, actor: UserCtx) -> PreferenceWorkingRead:
    # TODO: fetch working row + pointer hints from DB; compute period_status using org tz
    return PreferenceWorkingRead(
        doctor_id=doctor_id,
        year=year,
        month=month,
        unavailable_duty_days=[],
        unavailable_oncall_days=[],
        preferred_duty_days=[],
        preferred_oncall_days=[],
        min_duties_weekdays=0,
        max_duties_weekdays=None,
        min_duties_weekends=0,
        max_duties_weekends=None,
        min_oncall_weekdays=0,
        max_oncall_weekdays=None,
        min_oncall_weekends=0,
        max_oncall_weekends=None,
        weekend_back_to_back_allowed=True,
        preferred_partners=[],
        comments=None,
        status=PreferenceStatus.missing,
        version_id=None,
        submitted_at=None,
        submitted_by_role=None,
        submitted_by_user_id=None,
        last_admin_note=None,
        can_undo=False,
        can_redo=False,
        org_timezone=ORG_TZ,
        period_status=PeriodStatus(get_period_status(year, month)),
    )


def read_summary(*, year: int, month: int, actor: UserCtx) -> PreferencesSummaryRead:
    # TODO: aggregate from versions/pointers
    return PreferencesSummaryRead(
        year=year,
        month=month,
        submitted=[42, 7, 9],
        missing=[11, 13, 21],
        last_update_at=now_utc(),
    )


# ------------------------- Autosave / Checkpoint ---------------------------


def save_working_autosave(
    *,
    year: int,
    month: int,
    doctor_id: int,
    payload: PreferenceWorkingPut,
    actor: UserCtx,
) -> PreferenceAutosaveAck:
    # TODO: upsert into working table; do not touch versions/pointers
    now = now_utc()
    return PreferenceAutosaveAck(
        doctor_id=doctor_id,
        year=year,
        month=month,
        updated_at=now,
        status=PreferenceStatus.missing,
        version_id=None,
        can_undo=False,
        can_redo=False,
        lock_version=None,  # optional optimistic locking if you wire it
    )


def create_checkpoint(*, year: int, month: int, doctor_id: int, actor: UserCtx) -> PreferenceCheckpointCreated:
    # TODO: copy working → versions (new immutable), move pointer; mark submitter
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
    # TODO: move pointer to previous version; overwrite working; return current snapshot
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
    # TODO: move pointer to next version; overwrite working; return current snapshot
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


# ------------------------- Deadlines ---------------------------------------


def get_deadline(*, year: int, month: int, actor: UserCtx) -> PreferencesDeadlineRead:
    # TODO: read deadline row from DB
    return PreferencesDeadlineRead(
        year=year,
        month=month,
        deadline=now_utc(),
        status="open",
        org_timezone=ORG_TZ,
    )


def upsert_deadline(*, year: int, month: int, body: dict, actor: UserCtx) -> PreferencesDeadlinePut:
    # TODO: validate & upsert deadline in DB (org tz aware)
    return PreferencesDeadlinePut(
        year=year,
        month=month,
        deadline=now_utc(),
        status="open",
        org_timezone=ORG_TZ,
    )
