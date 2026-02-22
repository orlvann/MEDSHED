# backend/services/sms_service.py
"""
SMS Service.

Handles sending SMS messages via Twilio for:
- Deadline change notifications
- Deadline reminder notifications
"""

from __future__ import annotations

import logging

from backend.config import settings

logger = logging.getLogger(__name__)


def _get_twilio_client():
    """Lazily create Twilio client (only when SMS is actually sent)."""
    from twilio.rest import Client

    return Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)


def send_sms(*, phone_number: str, message: str) -> None:
    """
    Send an SMS via Twilio.

    Args:
        phone_number: Recipient phone number (E.164 format, e.g. +48123456789)
        message: SMS body text

    Notes:
        - Requires TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER in env
        - Failures are logged but not raised (non-blocking)
    """
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        logger.warning("Twilio credentials not configured — SMS not sent")
        return

    try:
        client = _get_twilio_client()
        client.messages.create(
            body=message,
            from_=settings.TWILIO_FROM_NUMBER,
            to=phone_number,
        )
        logger.info(f"SMS sent to {phone_number}")
    except Exception as e:
        logger.error(f"Failed to send SMS to {phone_number}: {e}")


def send_deadline_changed_sms(
    *,
    phone_number: str,
    first_name: str,
    last_name: str,
    year: int,
    month: int,
    new_deadline: str,
) -> None:
    """
    Send SMS notification when preferences deadline is changed.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from backend.utils.timez import ORG_TZ

    month_names = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    month_name = month_names[month - 1]

    deadline_dt = datetime.fromisoformat(new_deadline.replace("Z", "+00:00"))
    deadline_local = deadline_dt.astimezone(ZoneInfo(ORG_TZ))
    deadline_formatted = deadline_local.strftime("%B %d, %Y at %H:%M")

    message = (
        f"MedShed: The preferences deadline for {month_name} {year} has been updated. "
        f"New deadline: {deadline_formatted}."
    )
    send_sms(phone_number=phone_number, message=message)


def send_deadline_reminder_sms(
    *,
    phone_number: str,
    first_name: str,
    year: int,
    month: int,
    deadline: str,
    hours_before: int,
) -> None:
    """
    Send SMS reminder before deadline expires.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from backend.utils.timez import ORG_TZ

    month_names = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    month_name = month_names[month - 1]

    deadline_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
    deadline_local = deadline_dt.astimezone(ZoneInfo(ORG_TZ))
    deadline_formatted = deadline_local.strftime("%B %d, %Y at %H:%M")

    message = (
        f"MedShed: Reminder — the deadline for submitting preferences "
        f"for {month_name} {year} is in {hours_before} hours ({deadline_formatted})."
    )
    send_sms(phone_number=phone_number, message=message)
