"""
Edge-case demo seed: extreme availability patterns for availability + solver.

DEV-ONLY SCRIPT — do NOT run on production.

What this script does:

1. Ensures there is a pool of active doctors.
   - If doctors already exist in DB:
       -> uses all active doctors (is_active = True).
   - If there are no doctors:
       -> creates the same demo pool as in db_seed_demo.py:
          * 3 specialists
          * 3 residents
          * 1 inactive specialist (ignored in availability).

2. Chooses three FUTURE periods (edge-case months):
   - all_critical_period  -> every day has RiskLevel = critical
   - all_alert_period     -> every day has RiskLevel = alert
   - all_ok_period        -> every day has RiskLevel = ok

   By default:
   - base_year = today.year + 1
   - all_critical:  {year = base_year, month = 1}
   - all_alert:     {year = base_year, month = 2}
   - all_ok:        {year = base_year, month = 3}

   (All of them are "future" for get_period_status).

3. For each period it seeds preferences:

   3.1. ALL CRITICAL (no specialists available at all)
        - For each specialist:
            * unavailable_duty_days = all days in month
            * unavailable_oncall_days = all days in month
        - Residents stay fully available (no unavailable_* set).
        - Creates:
            * PreferenceWorking row per doctor
            * ONE PreferenceVersion checkpoint per doctor
            * PreferencePointer pointing to that checkpoint.

        Availability effect:
        - For every day:
            * total_specialists = 0
            * total_doctors > 0
          -> RiskLevel = critical (by _compute_risk_for_day rules).

      3.2. ALL ALERT (exactly one specialist available per day in risk sense)
        - If there is at least 1 specialist:
            * Picks the first specialist as available for ON_DUTY only
              (unavailable for ON_CALL on all days),
            * All other specialists are marked unavailable for ALL days
              (duty + on-call).
        - Residents stay fully available.
        - Same pattern: working + 1 checkpoint + pointer.

        Availability effect:
        - For every day:
            * exactly one specialist is available in total
              (spec_duty = 1, spec_oncall = 0),
            * total_specialists = 1 (below MIN_OK_SPECIALISTS_TOTAL = 2),
            * total_doctors is high (specialists + residents).
          -> RiskLevel = alert (not critical, not ok).

   3.3. ALL OK (everyone fully available)
        - Specialists + residents: no unavailable_* marks at all.
        - Same pattern: working + 1 checkpoint + pointer.

        Availability effect:
        - For every day:
            * total_duty   >= MIN_OK_DOCTORS_PER_CATEGORY
            * total_oncall >= MIN_OK_DOCTORS_PER_CATEGORY
            * total_specialists >= MIN_OK_SPECIALISTS_TOTAL
          -> RiskLevel = ok.

4. Idempotent-ish for chosen months:
   - Does NOT delete doctors, users, or preferences in other months.
   - For the three edge-case months it:
       * overwrites PreferenceWorking for active doctors,
       * creates NEW checkpoints in PreferenceVersion,
       * moves PreferencePointer to the newest checkpoint.

   If you run the script again, it will add more history for the same
   {year, month, doctor} but pointers will always point to the newest
   seeded version.

How to run (from repo root):

    PYTHONPATH=. python scripts/db_seed_edge_cases.py

After running, check in Swagger (admin token):

    - /api/v1/availability/overview?year=...&month=...
    - /api/v1/availability/{year}/{month}/{day}
    - /api/v1/preferences/{year}/{month}/{doctor_id}

Use the printed periods from script output as parameters.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import List, Sequence

from sqlalchemy import select

from backend.db.session import SessionLocal
from backend.models.common_enums import DoctorRole
from backend.models.orm.doctor import Doctor
from backend.models.orm.preference import (
    PreferencePointer,
    PreferenceVersion,
    PreferenceWorking,
)
from backend.utils.timez import now_utc

# Technical "user" id used for seed (no real User row required).
# It only satisfies the NOT NULL constraint on created_by_user_id.
SEED_EDGE_USER_ID = 0


@dataclass
class EdgePeriods:
    """Helper: keep all three edge periods together."""

    all_critical_year: int
    all_critical_month: int
    all_alert_year: int
    all_alert_month: int
    all_ok_year: int
    all_ok_month: int


def _pick_edge_periods() -> EdgePeriods:
    """
    Choose three future months for edge-case seeding.

    Strategy:
    - Base year = today.year + 1
    - Months: 1, 2, 3 (always in future vs "today").

    These periods do not collide with db_seed_demo.py, which uses
    current month + next month.
    """
    today = date.today()
    base_year = today.year + 1

    return EdgePeriods(
        all_critical_year=base_year,
        all_critical_month=1,
        all_alert_year=base_year,
        all_alert_month=2,
        all_ok_year=base_year,
        all_ok_month=3,
    )


def _days_in_month(year: int, month: int) -> int:
    """Return the real number of days in the given month/year."""
    _, num_days = calendar.monthrange(year, month)
    return num_days


def _ensure_demo_doctors(session) -> List[Doctor]:
    """
    Ensure there is a reasonable pool of active doctors.

    Rules:
    - If there are already doctors:
        -> return all active doctors (is_active = True).
    - If there are none:
        -> create 3 specialists + 3 residents + 1 inactive specialist.
    """
    active_doctors: List[Doctor] = (
        session.execute(select(Doctor).where(Doctor.is_active == True)).scalars().all()  # noqa: E712
    )
    if active_doctors:
        return active_doctors

    demo_doctors: List[Doctor] = []

    def add_doc(first_name: str, last_name: str, role: DoctorRole, email: str, is_active: bool = True) -> Doctor:
        """Create and add a single Doctor object."""
        doc = Doctor(
            first_name=first_name,
            last_name=last_name,
            role=role,
            email=email,
        )
        doc.is_active = is_active
        session.add(doc)
        demo_doctors.append(doc)
        return doc

    # 3 specialists
    add_doc("Alice", "Spec", DoctorRole.specialist, "alice.spec.edge@medsched.local", is_active=True)
    add_doc("Bob", "Spec", DoctorRole.specialist, "bob.spec.edge@medsched.local", is_active=True)
    add_doc("Carol", "Spec", DoctorRole.specialist, "carol.spec.edge@medsched.local", is_active=True)

    # 3 residents
    add_doc("Dan", "Res", DoctorRole.resident, "dan.res.edge@medsched.local", is_active=True)
    add_doc("Eva", "Res", DoctorRole.resident, "eva.res.edge@medsched.local", is_active=True)
    add_doc("Frank", "Res", DoctorRole.resident, "frank.res.edge@medsched.local", is_active=True)

    # 1 inactive specialist (kept in DB, ignored by availability)
    add_doc("Inactive", "Spec", DoctorRole.specialist, "inactive.spec.edge@medsched.local", is_active=False)

    session.flush()
    active_doctors = [d for d in demo_doctors if d.is_active]
    return active_doctors


def _payload_from_working(row: PreferenceWorking) -> dict:
    """
    Build JSON payload (dict) from editable fields of PreferenceWorking.

    This will be stored in PreferenceVersion.payload.
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
    - If not, create with defaults.
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
    """Get or create PreferencePointer for (doctor_id, year, month)."""
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


def _seed_period_all_critical(
    session,
    *,
    year: int,
    month: int,
    active_doctors: Sequence[Doctor],
) -> None:
    """
    Seed a period where all days are CRITICAL (no specialists available).

    Logic:
    - Specialists:
        * unavailable_* = ALL days in the month.
    - Residents:
        * no unavailability -> fully available.
    """
    now = now_utc()
    days_in_month = _days_in_month(year, month)
    all_days = list(range(1, days_in_month + 1))

    specialists = [d for d in active_doctors if d.role == DoctorRole.specialist]

    print(
        f"[edge] Seeding ALL-CRITICAL period {year}-{month:02d}: "
        f"days_in_month={days_in_month}, specialists={len(specialists)}, "
        f"active_doctors={len(active_doctors)}"
    )

    for doc in active_doctors:
        working = _ensure_working_row(session, doctor_id=doc.id, year=year, month=month)

        if doc.role == DoctorRole.specialist:
            # Specialists: never available in this period.
            working.unavailable_duty_days = all_days
            working.unavailable_oncall_days = all_days
        else:
            # Residents: fully available (no unavailable_*).
            working.unavailable_duty_days = []
            working.unavailable_oncall_days = []

        # Other fields – simple stable demo values.
        working.preferred_duty_days = []
        working.preferred_oncall_days = []

        working.min_duties_weekdays = 1
        working.max_duties_weekdays = 5
        working.min_duties_weekends = 0
        working.max_duties_weekends = 3
        working.min_oncall_weekdays = 0
        working.max_oncall_weekdays = 4
        working.min_oncall_weekends = 0
        working.max_oncall_weekends = 2

        working.weekend_back_to_back_allowed = True
        working.preferred_partners = []
        working.comments = f"edge all-critical period for doctor {doc.id}"

        working.last_saved_at = now
        working.last_saved_by_user_id = SEED_EDGE_USER_ID
        working.last_saved_by_role = "seed_edge_cases"
        working.lock_version = (working.lock_version or 0) + 1

        session.flush()
        payload = _payload_from_working(working)

        # Single checkpoint per doctor is enough to drive availability.
        version = PreferenceVersion(
            doctor_id=doc.id,
            year=year,
            month=month,
            kind="checkpoint",
            payload=payload,
            created_at=now,
            created_by_user_id=SEED_EDGE_USER_ID,
            created_by_role="seed_edge_cases",
            note=f"edge all-critical checkpoint for doctor {doc.id}",
        )
        session.add(version)
        session.flush()

        pointer = _ensure_pointer_row(session, doctor_id=doc.id, year=year, month=month)
        pointer.current_version_id = version.id
        pointer.submitted_at = now
        pointer.submitted_by_user_id = SEED_EDGE_USER_ID
        pointer.submitted_by_role = "seed_edge_cases"


def _seed_period_all_alert(
    session,
    *,
    year: int,
    month: int,
    active_doctors: Sequence[Doctor],
) -> None:
    """
    Seed a period where all days are ALERT (exactly one specialist in total).

    Logic:
    - If there is at least 1 specialist:
        * first specialist -> available for ON_DUTY only
          (unavailable for ON_CALL on all days),
        * all other specialists -> unavailable on ALL days (duty + on-call).
    - Residents:
        * fully available (no unavailable_*).
    """

    now = now_utc()
    days_in_month = _days_in_month(year, month)
    all_days = list(range(1, days_in_month + 1))

    specialists = [d for d in active_doctors if d.role == DoctorRole.specialist]
    residents = [d for d in active_doctors if d.role == DoctorRole.resident]

    print(
        f"[edge] Seeding ALL-ALERT period {year}-{month:02d}: "
        f"days_in_month={days_in_month}, specialists={len(specialists)}, "
        f"residents={len(residents)}, active_doctors={len(active_doctors)}"
    )

    if not specialists:
        print("[edge] No specialists in pool -> cannot form alert pattern, skipping.")
        return

    always_available_spec = specialists[0]

    for doc in active_doctors:
        working = _ensure_working_row(session, doctor_id=doc.id, year=year, month=month)

        if doc.role == DoctorRole.specialist:
            if doc.id == always_available_spec.id:
                # This specialist is available for ON_DUTY only.
                # He is marked unavailable for ON_CALL on all days.
                working.unavailable_duty_days = []
                working.unavailable_oncall_days = all_days
            else:
                # All other specialists are never available (duty + on-call).
                working.unavailable_duty_days = all_days
                working.unavailable_oncall_days = all_days
        else:
            # Residents fully available.
            working.unavailable_duty_days = []
            working.unavailable_oncall_days = []

        working.preferred_duty_days = []
        working.preferred_oncall_days = []

        working.min_duties_weekdays = 1
        working.max_duties_weekdays = 5
        working.min_duties_weekends = 0
        working.max_duties_weekends = 3
        working.min_oncall_weekdays = 0
        working.max_oncall_weekdays = 4
        working.min_oncall_weekends = 0
        working.max_oncall_weekends = 2

        working.weekend_back_to_back_allowed = True
        working.preferred_partners = []
        working.comments = f"edge all-alert period for doctor {doc.id}"

        working.last_saved_at = now
        working.last_saved_by_user_id = SEED_EDGE_USER_ID
        working.last_saved_by_role = "seed_edge_cases"
        working.lock_version = (working.lock_version or 0) + 1

        session.flush()
        payload = _payload_from_working(working)

        version = PreferenceVersion(
            doctor_id=doc.id,
            year=year,
            month=month,
            kind="checkpoint",
            payload=payload,
            created_at=now,
            created_by_user_id=SEED_EDGE_USER_ID,
            created_by_role="seed_edge_cases",
            note=f"edge all-alert checkpoint for doctor {doc.id}",
        )
        session.add(version)
        session.flush()

        pointer = _ensure_pointer_row(session, doctor_id=doc.id, year=year, month=month)
        pointer.current_version_id = version.id
        pointer.submitted_at = now
        pointer.submitted_by_user_id = SEED_EDGE_USER_ID
        pointer.submitted_by_role = "seed_edge_cases"


def _seed_period_all_ok(
    session,
    *,
    year: int,
    month: int,
    active_doctors: Sequence[Doctor],
) -> None:
    """
    Seed a period where all days are OK (everyone fully available).

    Logic:
    - Specialists + residents:
        * no unavailable_* marks at all.
    """
    now = now_utc()
    days_in_month = _days_in_month(year, month)

    print(
        f"[edge] Seeding ALL-OK period {year}-{month:02d}: "
        f"days_in_month={days_in_month}, active_doctors={len(active_doctors)}"
    )

    for doc in active_doctors:
        working = _ensure_working_row(session, doctor_id=doc.id, year=year, month=month)

        # Fully available, no unavailability lists.
        working.unavailable_duty_days = []
        working.unavailable_oncall_days = []
        working.preferred_duty_days = []
        working.preferred_oncall_days = []

        working.min_duties_weekdays = 1
        working.max_duties_weekdays = 5
        working.min_duties_weekends = 0
        working.max_duties_weekends = 3
        working.min_oncall_weekdays = 0
        working.max_oncall_weekdays = 4
        working.min_oncall_weekends = 0
        working.max_oncall_weekends = 2

        working.weekend_back_to_back_allowed = True
        working.preferred_partners = []
        working.comments = f"edge all-ok period for doctor {doc.id}"

        working.last_saved_at = now
        working.last_saved_by_user_id = SEED_EDGE_USER_ID
        working.last_saved_by_role = "seed_edge_cases"
        working.lock_version = (working.lock_version or 0) + 1

        session.flush()
        payload = _payload_from_working(working)

        version = PreferenceVersion(
            doctor_id=doc.id,
            year=year,
            month=month,
            kind="checkpoint",
            payload=payload,
            created_at=now,
            created_by_user_id=SEED_EDGE_USER_ID,
            created_by_role="seed_edge_cases",
            note=f"edge all-ok checkpoint for doctor {doc.id}",
        )
        session.add(version)
        session.flush()

        pointer = _ensure_pointer_row(session, doctor_id=doc.id, year=year, month=month)
        pointer.current_version_id = version.id
        pointer.submitted_at = now
        pointer.submitted_by_user_id = SEED_EDGE_USER_ID
        pointer.submitted_by_role = "seed_edge_cases"


def main() -> None:
    """Entry point for edge-case demo seed."""
    db = SessionLocal()
    try:
        periods = _pick_edge_periods()
        print(
            "[edge] Edge-case periods:"
            f" ALL-CRITICAL={periods.all_critical_year}-{periods.all_critical_month:02d},"
            f" ALL-ALERT={periods.all_alert_year}-{periods.all_alert_month:02d},"
            f" ALL-OK={periods.all_ok_year}-{periods.all_ok_month:02d}"
        )

        # 1) Ensure active doctors.
        active_doctors = _ensure_demo_doctors(db)
        doctor_summaries = [(d.id, d.first_name, d.last_name, d.role.value) for d in active_doctors]
        print("[edge] Active doctors in DB:", doctor_summaries)

        if not active_doctors:
            print("[edge] No active doctors found or created. Nothing to seed.")
            db.commit()
            return

        # 2) Seed the three edge periods.
        _seed_period_all_critical(
            db,
            year=periods.all_critical_year,
            month=periods.all_critical_month,
            active_doctors=active_doctors,
        )
        _seed_period_all_alert(
            db,
            year=periods.all_alert_year,
            month=periods.all_alert_month,
            active_doctors=active_doctors,
        )
        _seed_period_all_ok(
            db,
            year=periods.all_ok_year,
            month=periods.all_ok_month,
            active_doctors=active_doctors,
        )

        db.commit()

        print("\n== Edge-case demo seed complete ==")
        print(
            f"ALL-CRITICAL period : {periods.all_critical_year}-"
            f"{periods.all_critical_month:02d} (no specialists available)."
        )
        print(
            f"ALL-ALERT period    : {periods.all_alert_year}-"
            f"{periods.all_alert_month:02d} (exactly one specialist available)."
        )
        print(f"ALL-OK period       : {periods.all_ok_year}-" f"{periods.all_ok_month:02d} (everyone fully available).")
        print("\nCheck Swagger with admin user:")
        print("  - /api/v1/availability/overview?year=...&month=...")
        print("  - /api/v1/availability/{year}/{month}/{day}")
        print("  - /api/v1/preferences/{year}/{month}/{doctor_id}")
        print("Use the printed periods above as parameters.\n")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
