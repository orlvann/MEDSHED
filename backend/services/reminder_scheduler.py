# backend/services/reminder_scheduler.py
"""
Reminder Scheduler.

Periodically checks upcoming deadlines and sends reminder notifications
(email + SMS) to active doctors at 24h and 2h before each deadline.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from backend.db.session import SessionLocal
from backend.models.orm.deadline_reminder import DeadlineReminderSent
from backend.models.orm.doctor import Doctor
from backend.models.orm.preference import PreferenceDeadline
from backend.services.email_service import send_deadline_reminder_email
from backend.services.sms_service import send_deadline_reminder_sms

logger = logging.getLogger(__name__)

# Reminder thresholds in hours
REMINDER_THRESHOLDS = [
    (24, "24h"),
    (2, "2h"),
]


def check_and_send_reminders() -> None:
    """
    Check all upcoming deadlines and send reminders if needed.

    For each PreferenceDeadline where deadline_utc > now:
    - If <= 24h remaining and "24h" reminder not sent -> send
    - If <= 2h remaining and "2h" reminder not sent -> send
    """
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        now_naive = now.replace(tzinfo=None)

        # Get future deadlines
        deadlines = (
            db.query(PreferenceDeadline)
            .filter(PreferenceDeadline.deadline_utc > now_naive)
            .all()
        )

        for deadline in deadlines:
            # Ensure timezone-aware comparison (SQLite may return naive)
            deadline_dt = deadline.deadline_utc
            if deadline_dt.tzinfo is None:
                deadline_dt = deadline_dt.replace(tzinfo=timezone.utc)

            remaining = deadline_dt - now
            remaining_hours = remaining.total_seconds() / 3600

            for threshold_hours, reminder_type in REMINDER_THRESHOLDS:
                if remaining_hours > threshold_hours:
                    continue

                # Check if already sent
                already_sent = (
                    db.query(DeadlineReminderSent)
                    .filter(
                        DeadlineReminderSent.deadline_id == deadline.id,
                        DeadlineReminderSent.reminder_type == reminder_type,
                    )
                    .first()
                )
                if already_sent:
                    continue

                # Send reminders to all active doctors
                active_doctors = (
                    db.query(Doctor)
                    .filter(Doctor.is_active.is_(True))
                    .all()
                )

                deadline_iso = deadline_dt.isoformat()

                for doctor in active_doctors:
                    if doctor.email:
                        try:
                            send_deadline_reminder_email(
                                email=doctor.email,
                                first_name=doctor.first_name,
                                last_name=doctor.last_name,
                                year=deadline.year,
                                month=deadline.month,
                                deadline=deadline_iso,
                                hours_before=threshold_hours,
                            )
                        except Exception:
                            logger.exception(
                                "Failed to send reminder email to %s", doctor.email
                            )

                    if doctor.phone_number:
                        try:
                            send_deadline_reminder_sms(
                                phone_number=doctor.phone_number,
                                first_name=doctor.first_name,
                                year=deadline.year,
                                month=deadline.month,
                                deadline=deadline_iso,
                                hours_before=threshold_hours,
                            )
                        except Exception:
                            logger.exception(
                                "Failed to send reminder SMS to %s", doctor.phone_number
                            )

                # Mark reminder as sent
                record = DeadlineReminderSent(
                    deadline_id=deadline.id,
                    reminder_type=reminder_type,
                )
                db.add(record)
                db.commit()

    except Exception:
        logger.exception("Reminder check failed")
        db.rollback()
    finally:
        db.close()


# Module-level scheduler instance
_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> None:
    """Start the background reminder scheduler (runs every 5 minutes)."""
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        check_and_send_reminders,
        "interval",
        minutes=5,
        id="deadline_reminders",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),  # run immediately on startup
    )
    _scheduler.start()
    logger.info("Reminder scheduler started (interval: 5 min)")


def stop_scheduler() -> None:
    """Stop the background reminder scheduler."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Reminder scheduler stopped")
