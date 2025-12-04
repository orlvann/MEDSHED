# backend/models/orm/user.py
"""
Users ORM — current vs target (concise)

NOW:
- email (unique, NOT NULL), role: Enum("admin"|"doctor")
- password_hash, is_active (login gate)
- optional doctor_id (1:1 → doctors.id, unique; admins have NULL)
- created_at, updated_at (UTC)
- Constraints: uq_users_email, uq_users_doctor_id; Index: ix_users_role
- Policy: doctors.is_active DOES NOT affect login; only users.is_active does.

TARGET (future migrations/services):
- must_change_password (BOOL, default True on creation for ALL new users)
- deactivated_at (timestamptz) — when login disabled (is_active=False)
- deleted_at (timestamptz) — logical removal marker (alt to hard delete)
- Auto-provision in doctor_service: on POST /doctors with unique email → create linked user
  (role=doctor, is_active=True, must_change_password=True). Email updates propagate; 409 on duplicates.
- Soft/hard delete behavior handled in services (no cascade deletes here).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.session import Base
from backend.models.common_enums import UserRole  # "admin" | "doctor" | "doctor_admin"


class User(Base):
    """
    Auth user account.
    - Everyone logs in with email + password_hash.
    - role controls permissions ("admin" | "doctor").
    - doctor users can be linked 1:1 to a Doctor row via doctor_id.
    """

    __tablename__ = "users"

    # Identity
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)  # unique via named constraint below
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole, name="user_role", validate_strings=True), nullable=False)

    # Auth
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    # Optional link to Doctor (1:1)
    # - admins: doctor_id = NULL
    # - doctors: doctor_id points to doctors.id (unique ensures at most one user per doctor)
    doctor_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("doctors.id", ondelete="SET NULL"),
        nullable=True,
    )
    doctor = relationship("Doctor", uselist=False)  # optional, convenience access

    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # Email must be unique (NULL not allowed, so strict uniqueness)
        UniqueConstraint("email", name="uq_users_email"),
        # Enforce 1:1 mapping from Doctor -> User (allows multiple NULLs)
        UniqueConstraint("doctor_id", name="uq_users_doctor_id"),
        # Helpful indexes
        Index("ix_users_role", "role"),
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} role={self.role.value} active={self.is_active}>"
