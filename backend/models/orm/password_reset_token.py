# backend/models/orm/password_reset_token.py
"""
Password Reset Token ORM — secure one-time token for password setup/reset.

Purpose:
- Store tokens separately from users table for security and auditability
- One active token per user (enforced by unique constraint on user_id)
- Tokens expire after configured time (default 48 hours)
- Tokens are consumed (deleted) after successful password reset

Security:
- Token is cryptographically secure (64+ chars, URL-safe)
- Index on token for fast lookup
- Unique constraint prevents multiple active tokens per user
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.session import Base


class PasswordResetToken(Base):
    """
    ORM model for password reset tokens.
    Used for initial password setup and password reset flows.
    """

    __tablename__ = "password_reset_tokens"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Foreign key to users table (unique: one active token per user)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # The actual token (long, random, URL-safe)
    token: Mapped[str] = mapped_column(String(128), nullable=False)

    # Expiration timestamp
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Creation timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # Ensure only one active token per user
        UniqueConstraint("user_id", name="uq_password_reset_tokens_user_id"),
        # Fast lookup by token
        UniqueConstraint("token", name="uq_password_reset_tokens_token"),
        Index("ix_password_reset_tokens_token", "token"),
        Index("ix_password_reset_tokens_expires_at", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<PasswordResetToken id={self.id} user_id={self.user_id} expires={self.expires_at}>"

