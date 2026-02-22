# backend/models/orm/doctor.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.session import Base
from backend.models.common_enums import DoctorRole  # enums: single source of truth


class Doctor(Base):
    """
    SQLAlchemy ORM for the 'doctors' table.
    Matches DTOs: DoctorCreate / DoctorPut / DoctorRead / DoctorMini.
    """

    __tablename__ = "doctors"

    # --- Primary key ---
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # --- Names ---
    first_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # --- Role (backed by shared Python Enum) ---
    # name="doctor_role" defines a stable ENUM type in Postgres (important for migrations).
    role: Mapped[DoctorRole] = mapped_column(
        SAEnum(DoctorRole, name="doctor_role", validate_strings=True),
        nullable=False,
    )

    # --- Flags ---
    # server_default ensures safe defaults when rows are inserted from SQL.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    is_head: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    # --- Email (optional, unique) ---
    # Note: NULLs do not violate uniqueness in Postgres; multiple NULLs allowed.
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)

    # --- Calendar feed token (UUID for public ICS subscription URL) ---
    calendar_feed_token: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, unique=True, index=True
    )

    # --- Timestamps (timezone-aware, server-managed) ---
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # Composite index to speed up lookups by last_name + role (example)
        Index("ix_doctors_last_name_role", "last_name", "role"),
        # Explicit unique constraint name for clarity and stable migrations
        UniqueConstraint("email", name="uq_doctors_email"),
        UniqueConstraint("calendar_feed_token", name="uq_doctors_calendar_feed_token"),
    )

    def __repr__(self) -> str:
        return (
            f"<Doctor id={self.id} {self.first_name} {self.last_name} "
            f"role={self.role.value} active={self.is_active}>"
        )
