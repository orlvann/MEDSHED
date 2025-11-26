"""
Demo seed: doctors + monthly preferences + availability patterns.

What this script does (DEV ONLY):

1. Ensures there are some active doctors in the DB.
   - If there are no doctors at all → creates a small demo pool:
     * 3 specialists
     * 3 residents
     * 1 inactive specialist (is_active = False, ignored by availability/summary).

2. Defines two periods based on *today*:
   - locked_period  = {year = today.year, month = today.month}
       * creates a PreferenceDeadline with deadline_utc in the past
         → for this period, doctor-facing endpoints (/me/...) are locked.
       * No preferences are created for this period (forms are simply locked).
   - open_period    = next calendar month after locked_period
       * no deadline row → forms are open until the month becomes 'past'.

3. For the OPEN period only:
   - Uses all active doctors (Doctor.is_active = True).
   - Splits them into three groups:
       * multi_checkpoint_docs: first 3 doctors
           - get PreferenceWorking + 3 PreferenceVersion checkpoints
           - have a PreferencePointer pointing to the newest checkpoint
           - represent "submitted with history".
       * working_only_docs: next 2 doctors
           - get PreferenceWorking only (no checkpoints, no pointer)
           - appear as "missing" in summary until a checkpoint is created.
       * no_data_docs: the rest
           - have no working / no checkpoints → completely missing.

   - Sets availability patterns so that:
       * one day is CLEARLY OK        (enough specialists + residents)
       * one day is ALERT             (only 1 specialist available)
       * one day is CRITICAL          (no specialists available at all,
                                       only residents are available)

   These patterns are visible in:
       - GET /api/v1/availability/overview
       - GET /api/v1/availability/{year}/{month}/{day}

4. Idempotent-ish:
   - Does NOT delete existing doctors or users.
   - For preferences in the OPEN period, it overwrites working rows
     for the selected demo doctors and (re)creates checkpoints/pointers.
   - For deadlines in the LOCKED period, it upserts a single row
     with a deadline in the past.

How to run (from repo root):

    PYTHONPATH=. python scripts/db_seed_demo.py

After running, test manually in Swagger:

    - /api/v1/preferences/deadlines/{year}/{month}
    - /api/v1/preferences/summary?year=...&month=...      (admin)
    - /api/v1/preferences/{year}/{month}/{doctor_id}      (admin read)
    - /api/v1/availability/overview?year=...&month=...    (admin)
    - /api/v1/availability/{year}/{month}/{day}           (admin)

The script prints the chosen periods and a short summary at the end.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Sequence, Tuple

from sqlalchemy import select

from backend.db.session import SessionLocal
from backend.models.common_enums import DoctorRole
from backend.models.orm.doctor import Doctor
from backend.models.orm.preference import (
    PreferenceDeadline,
    PreferencePointer,
    PreferenceVersion,
    PreferenceWorking,
)
from backend.utils.timez import ORG_TZ, now_utc

# Technical user id used for demo seed (no real User row required)
SEED_DEMO_USER_ID = 0


@dataclass
class DemoPeriods:
    """Small helper to keep both periods together."""

    locked_year: int
    locked_month: int
    open_year: int
    open_month: int


def _pick_demo_periods() -> DemoPeriods:
    """
    Choose two periods based on today's date.

    - locked_period = current month
    - open_period   = next month (wraps year when month == 12)
    """
    today = date.today()
    locked_year = today.year
    locked_month = today.month

    if locked_month == 12:
        open_year = locked_year + 1
        open_month = 1
    else:
        open_year = locked_year
        open_month = locked_month + 1

    return DemoPeriods(
        locked_year=locked_year,
        locked_month=locked_month,
        open_year=open_year,
        open_month=open_month,
    )


def _ensure_demo_doctors(session) -> List[Doctor]:
    """
    Ensure there is a reasonable pool of active doctors.

    Rules:
    - If there are already doctors in the DB:
        -> return all active doctors (is_active = True).
    - If there are none:
        -> create 3 specialists + 3 residents + 1 inactive specialist.
           All emails are unique for clarity.
    """
    # Read any existing doctors first.
    active_doctors: List[Doctor] = (
        session.execute(select(Doctor).where(Doctor.is_active == True)).scalars().all()  # noqa: E712
    )
    if active_doctors:
        # DB already has doctors → use them as the demo pool.
        return active_doctors

    # No doctors at all → create a small demo pool.
    demo_doctors: List[Doctor] = []

    def add_doc(first_name: str, last_name: str, role: DoctorRole, email: str, is_active: bool = True) -> Doctor:
        """Create and add a single Doctor object."""
        doc = Doctor(
            first_name=first_name,
            last_name=last_name,
            role=role,
            email=email,
        )
        doc.is_active = is_active  # make the intent explicit
        session.add(doc)
        demo_doctors.append(doc)
        return doc

    # 3 demo specialists
    add_doc("Alice", "Spec", DoctorRole.specialist, "alice.spec.demo@medsched.local", is_active=True)
    add_doc("Bob", "Spec", DoctorRole.specialist, "bob.spec.demo@medsched.local", is_active=True)
    add_doc("Carol", "Spec", DoctorRole.specialist, "carol.spec.demo@medsched.local", is_active=True)

    # 3 demo residents
    add_doc("Dan", "Res", DoctorRole.resident, "dan.res.demo@medsched.local", is_active=True)
    add_doc("Eva", "Res", DoctorRole.resident, "eva.res.demo@medsched.local", is_active=True)
    add_doc("Frank", "Res", DoctorRole.resident, "frank.res.demo@medsched.local", is_active=True)

    # 1 inactive doctor (will NOT be counted in summary/availability)
    add_doc("Inactive", "Spec", DoctorRole.specialist, "inactive.spec.demo@medsched.local", is_active=False)

    session.flush()
    # Return only active ones (inactive doctor stays in DB but is ignored).
    active_doctors = [d for d in demo_doctors if d.is_active]
    return active_doctors


def _upsert_locked_deadline(session, *, year: int, month: int) -> PreferenceDeadline:
    """
    Create or update a deadline row for (year, month) with a past UTC timestamp.

    Effect:
    - For this period, PreferenceDeadline exists and deadline_utc < now_utc().
    - is_doctor_locked_for_period(...) will treat it as LOCKED (for doctors).
    """
    deadline_utc = now_utc() - timedelta(days=1)

    row: PreferenceDeadline | None = (
        session.execute(
            select(PreferenceDeadline).where(
                PreferenceDeadline.year == year,
                PreferenceDeadline.month == month,
            )
        )
        .scalars()
        .one_or_none()
    )

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

    session.flush()
    return row


def _days_in_month(year: int, month: int) -> int:
    """Return the real number of days in the given month/year."""
    _, num_days = calendar.monthrange(year, month)
    return num_days


def _pick_special_days(year: int, month: int) -> Tuple[int, int, int]:
    """
    Choose 3 day numbers inside the month for 'critical', 'ok', and 'alert' scenarios.

    Returns:
        (day_critical, day_ok, day_alert)
    """
    days = _days_in_month(year, month)

    # Keep them simple but always inside range.
    day_critical = 5 if days >= 5 else 1
    day_ok = 10 if days >= 10 else days
    if days >= 15:
        day_alert = 15
    else:
        # fallback: pick a different day from critical/ok if possible
        if days >= 3:
            day_alert = 3
        elif days >= 2:
            day_alert = 2
        else:
            day_alert = 1

    return day_critical, day_ok, day_alert


def _build_unavailable_for_doctor(
    doc: Doctor,
    *,
    specialists: Sequence[Doctor],
    day_critical: int,
    day_alert: int,
) -> Tuple[list[int], list[int]]:
    """
    Build unavailable_duty_days and unavailable_oncall_days for a single doctor.

    Rules for demo:
    - day_critical:
        * all specialists are unavailable (duty + on-call)
        * residents stay available.
    - day_alert:
        * exactly one specialist is partially available:
            - the first specialist in `specialists`:
                available for DUTY, unavailable for ON-CALL
        * all remaining specialists are unavailable (duty + on-call)
        * residents stay fully available.

    For other days we do not mark anything → fully available.
    """
    unavailable_duty: set[int] = set()
    unavailable_oncall: set[int] = set()

    if doc.role == DoctorRole.specialist:
        # All specialists unavailable on the critical day.
        unavailable_duty.add(day_critical)
        unavailable_oncall.add(day_critical)

        if specialists:
            first_specialist = specialists[0]
            if doc.id == first_specialist.id:
                # First specialist: only ON-CALL blocked on alert day.
                unavailable_oncall.add(day_alert)
            else:
                # Other specialists: fully unavailable on alert day.
                unavailable_duty.add(day_alert)
                unavailable_oncall.add(day_alert)

    # Residents: we do not mark them unavailable for those demo days,
    # so they stay available and help form alert/critical combinations.

    return sorted(unavailable_duty), sorted(unavailable_oncall)


def _payload_from_working(row: PreferenceWorking) -> dict:
    """
    Build JSON payload (dict) from editable fields of PreferenceWorking.

    This mirrors the service helper and is stored in PreferenceVersion.payload.
    """
    return {
        "unavailable_duty_days": row.unavailable_duty_days or [],
        "unavailable_oncall_days": row.unavailable_oncall_days or [],
        "preferred_duty_days": row.preferred_duty_days or [],
        "preferred_oncall_days": row.preferred_oncall_days or [],
        "min_duties_weekdays": row.min_duties_weekdays,
        "max_duties_weekdays": row.max_duties_weekdays,
        "min_duties_weekends": row.min_duties_weekends,
        "max_duties_weekends": row.max_duties_weekends,
        "min_oncall_weekdays": row.min_oncall_weekdays,
        "max_oncall_weekdays": row.max_oncall_weekdays,
        "min_oncall_weekends": row.min_oncall_weekends,
        "max_oncall_weekends": row.max_oncall_weekends,
        "weekend_back_to_back_allowed": row.weekend_back_to_back_allowed,
        "preferred_partners": row.preferred_partners or [],
        "comments": row.comments,
    }


def _ensure_working_row(
    session,
    *,
    doctor_id: int,
    year: int,
    month: int,
) -> PreferenceWorking:
    """
    Get or create PreferenceWorking for (doctor_id, year, month).

    - If row exists, return it.
    - If not, create with default values and return it.
    """
    row: PreferenceWorking | None = (
        session.execute(
            select(PreferenceWorking).where(
                PreferenceWorking.doctor_id == doctor_id,
                PreferenceWorking.year == year,
                PreferenceWorking.month == month,
            )
        )
        .scalars()
        .one_or_none()
    )
    if row is None:
        row = PreferenceWorking(
            doctor_id=doctor_id,
            year=year,
            month=month,
        )
        session.add(row)
        session.flush()
    return row


def _ensure_pointer_row(
    session,
    *,
    doctor_id: int,
    year: int,
    month: int,
) -> PreferencePointer:
    """
    Get or create PreferencePointer for (doctor_id, year, month).
    """
    pointer: PreferencePointer | None = (
        session.execute(
            select(PreferencePointer).where(
                PreferencePointer.doctor_id == doctor_id,
                PreferencePointer.year == year,
                PreferencePointer.month == month,
            )
        )
        .scalars()
        .one_or_none()
    )
    if pointer is None:
        pointer = PreferencePointer(
            doctor_id=doctor_id,
            year=year,
            month=month,
        )
        session.add(pointer)
        session.flush()
    return pointer


def _seed_open_period_preferences(
    session,
    *,
    year: int,
    month: int,
    active_doctors: Sequence[Doctor],
) -> None:
    """
    Seed PreferenceWorking + PreferenceVersion + PreferencePointer for OPEN period.

    Groups:
    - first 3 active doctors         -> working + 3 checkpoints + pointer
    - next 2 active doctors          -> working only (no checkpoints)
    - the rest                       -> no data

    Availability patterns:
    - choose special days (critical/ok/alert).
    - for each specialist/resident, set unavailable_* so that:
        * day_critical: no specialists available
        * day_alert:    exactly one specialist available
        * day_ok:       plenty of doctors available
      (day_ok is kept free of unavailability marks here).
    """
    if not active_doctors:
        print("No active doctors available for open period: skipping preference seeding.")
        return

    # Split by role for availability patterns.
    specialists = [d for d in active_doctors if d.role == DoctorRole.specialist]
    # Residents stay fully available in this simple demo, so we don't need a separate list.

    day_critical, day_ok, day_alert = _pick_special_days(year, month)
    days_in_month = _days_in_month(year, month)

    print(
        f"[demo] Open period {year}-{month:02d}: "
        f"days_in_month={days_in_month}, critical={day_critical}, ok={day_ok}, alert={day_alert}"
    )

    # Group doctors for history / working presence.
    # Order is stable but does not matter for business logic.
    all_active = list(active_doctors)
    multi_checkpoint_docs: List[Doctor] = all_active[:3]
    working_only_docs: List[Doctor] = all_active[3:5]
    no_data_docs: List[Doctor] = all_active[5:]

    now = now_utc()

    # 1) Multi-checkpoint doctors: working + 3 checkpoints + pointer.
    for doc in multi_checkpoint_docs:
        working = _ensure_working_row(session, doctor_id=doc.id, year=year, month=month)

        # Build unavailable_* lists based on role and special days.
        unavailable_duty, unavailable_oncall = _build_unavailable_for_doctor(
            doc,
            specialists=specialists,
            day_critical=day_critical,
            day_alert=day_alert,
        )

        # Fill editable fields.
        working.unavailable_duty_days = unavailable_duty
        working.unavailable_oncall_days = unavailable_oncall
        working.preferred_duty_days = []  # not used by availability
        working.preferred_oncall_days = []

        # Simple min/max settings for demo.
        working.min_duties_weekdays = 2
        working.max_duties_weekdays = 5
        working.min_duties_weekends = 0
        working.max_duties_weekends = 3
        working.min_oncall_weekdays = 1
        working.max_oncall_weekdays = 4
        working.min_oncall_weekends = 0
        working.max_oncall_weekends = 2

        working.weekend_back_to_back_allowed = True
        working.preferred_partners = []
        working.comments = f"demo working for doctor {doc.id}"

        # Audit + lock_version.
        working.last_saved_at = now
        working.last_saved_by_user_id = None
        working.last_saved_by_role = "seed_demo"
        working.lock_version = (working.lock_version or 0) + 1

        session.flush()
        payload = _payload_from_working(working)

        # Create 3 checkpoints with the same payload (good enough for UNDO/REDO testing).
        versions: list[PreferenceVersion] = []
        for i in range(3):
            v = PreferenceVersion(
                doctor_id=doc.id,
                year=year,
                month=month,
                kind="checkpoint",
                payload=payload,
                created_at=now - timedelta(minutes=10 * (2 - i)),  # v1 older, v3 newest
                created_by_user_id=SEED_DEMO_USER_ID,
                created_by_role="seed_demo",
                note=f"demo checkpoint #{i+1} for doctor {doc.id}",
            )
            session.add(v)
            session.flush()
            versions.append(v)

        # Pointer goes to the newest version (last in list).
        latest_version = versions[-1]
        pointer = _ensure_pointer_row(session, doctor_id=doc.id, year=year, month=month)
        pointer.current_version_id = latest_version.id
        pointer.submitted_at = now
        pointer.submitted_by_user_id = None
        pointer.submitted_by_role = "seed_demo"

    # 2) Working-only doctors: working rows without checkpoints/pointers.
    for doc in working_only_docs:
        working = _ensure_working_row(session, doctor_id=doc.id, year=year, month=month)

        unavailable_duty, unavailable_oncall = _build_unavailable_for_doctor(
            doc,
            specialists=specialists,
            day_critical=day_critical,
            day_alert=day_alert,
        )

        working.unavailable_duty_days = unavailable_duty
        working.unavailable_oncall_days = unavailable_oncall
        working.preferred_duty_days = []
        working.preferred_oncall_days = []

        working.min_duties_weekdays = 1
        working.max_duties_weekdays = 3
        working.min_duties_weekends = 0
        working.max_duties_weekends = 2
        working.min_oncall_weekdays = 0
        working.max_oncall_weekdays = 2
        working.min_oncall_weekends = 0
        working.max_oncall_weekends = 1

        working.weekend_back_to_back_allowed = True
        working.preferred_partners = []
        working.comments = f"demo working-only (no checkpoints) for doctor {doc.id}"

        working.last_saved_at = now
        working.last_saved_by_user_id = None
        working.last_saved_by_role = "seed_demo"
        working.lock_version = (working.lock_version or 0) + 1

        session.flush()
        # No PreferenceVersion / PreferencePointer on purpose.

    # 3) No-data doctors: we do nothing for (year, month).
    if no_data_docs:
        ids = [d.id for d in no_data_docs]
        print(f"[demo] Doctors with NO data for open period {year}-{month:02d}: {ids}")


def main() -> None:
    """Entry point for the demo seed."""
    db = SessionLocal()
    try:
        periods = _pick_demo_periods()
        print(
            f"[demo] Locked period: {periods.locked_year}-{periods.locked_month:02d}, "
            f"Open period: {periods.open_year}-{periods.open_month:02d}"
        )

        # 1) Ensure we have a pool of active doctors.
        active_doctors = _ensure_demo_doctors(db)
        # Build a simple summary list for logging
        doctor_summaries = [(d.id, d.first_name, d.last_name, d.role.value) for d in active_doctors]

        print("[demo] Active doctors in DB:", doctor_summaries)

        if not active_doctors:
            print("[demo] No active doctors found or created. Nothing more to seed.")
            db.commit()
            return

        # 2) Upsert a locked deadline for the current month (locked period).
        locked_deadline = _upsert_locked_deadline(
            db,
            year=periods.locked_year,
            month=periods.locked_month,
        )
        print(
            f"[demo] Locked deadline set for {locked_deadline.year}-{locked_deadline.month:02d} "
            f"deadline_utc={locked_deadline.deadline_utc.isoformat()} "
            f"org_tz={locked_deadline.org_timezone}"
        )

        # 3) Seed preferences for the open period (no deadline row).
        _seed_open_period_preferences(
            db,
            year=periods.open_year,
            month=periods.open_month,
            active_doctors=active_doctors,
        )

        db.commit()

        print("\n== Demo seed complete ==")
        print(
            f"Locked period  : {periods.locked_year}-{periods.locked_month:02d} "
            f"(has past deadline, no preferences seeded)"
        )
        print(
            f"Open period    : {periods.open_year}-{periods.open_month:02d} "
            f"(demo preferences + checkpoints created)"
        )
        print("Check Swagger for:")
        print("  - /api/v1/preferences/deadlines/{year}/{month}")
        print("  - /api/v1/preferences/summary?year=...&month=...")
        print("  - /api/v1/availability/overview?year=...&month=...")
        print("  - /api/v1/availability/{year}/{month}/{day}")
        print("Use the printed periods above as parameters.\n")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
