# backend/models/orm/deadline_reminder.py
"""
DeadlineReminderSent ORM Model.

Tracks which reminder notifications have been sent for each deadline,
preventing duplicate reminders.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.db.session import Base


class DeadlineReminderSent(Base):
    """
    Tracks sent deadline reminders to avoid duplicates.

    Each (deadline_id, reminder_type) pair can only exist once,
    ensuring reminders are sent exactly once.
    """

    __tablename__ = "deadline_reminders_sent"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deadline_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("preferences_deadlines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reminder_type: Mapped[str] = mapped_column(String(10), nullable=False)  # "24h" or "2h"
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("deadline_id", "reminder_type", name="uq_deadline_reminder"),)

    def __repr__(self) -> str:
        return f"<DeadlineReminderSent deadline_id={self.deadline_id} type={self.reminder_type}>"
