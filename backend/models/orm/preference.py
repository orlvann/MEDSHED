# backend/models/orm/preference.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.session import Base


# --- PREFERENCES_WORKING -----------------------------------------------------
class PreferenceWorking(Base):
    """
    One editable row per (doctor_id, year, month).
    Holds current 'working' state (form) for the given period and doctor.
    """

    __tablename__ = "preferences_working"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    doctor_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("doctors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)

    # OCC token (prepared now, used after MVP)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    # Editable fields (mirroring DTO; use JSON/TEXT arrays for day lists)
    # Day-level preferences (calendar days 1..31)
    unavailable_onsite_days: Mapped[Optional[list[int]]] = mapped_column(JSON, default=list)
    unavailable_oncall_days: Mapped[Optional[list[int]]] = mapped_column(JSON, default=list)
    preferred_onsite_days: Mapped[Optional[list[int]]] = mapped_column(JSON, default=list)
    preferred_oncall_days: Mapped[Optional[list[int]]] = mapped_column(JSON, default=list)

    # Monthly totals (soft constraints; some fields are future-only)
    min_onsite_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # future: not used in MVP
    max_onsite_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    target_onsite_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    min_oncall_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # future: not used in MVP
    max_oncall_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    target_oncall_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Weekend refinement (optional, advanced)
    max_onsite_weekends: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    target_onsite_weekends: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_oncall_weekends: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    target_oncall_weekends: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Weekday patterns (0=Monday..6=Sunday)
    preferred_onsite_weekdays: Mapped[Optional[list[int]]] = mapped_column(JSON, default=list)
    preferred_oncall_weekdays: Mapped[Optional[list[int]]] = mapped_column(JSON, default=list)
    avoid_onsite_weekdays: Mapped[Optional[list[int]]] = mapped_column(JSON, default=list)
    avoid_oncall_weekdays: Mapped[Optional[list[int]]] = mapped_column(JSON, default=list)

    # Other preferences
    allow_weekend_consecutive_onsite_oncall: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    preferred_partners: Mapped[Optional[list[int]]] = mapped_column(JSON, default=list)
    comments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Audit (not OCC token; for UX)
    last_saved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_saved_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_saved_by_role: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    last_admin_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("doctor_id", "year", "month", name="uq_working_doctor_period"),
        CheckConstraint("month >= 1 AND month <= 12", name="ck_working_month_range"),
        CheckConstraint("year >= 1900 AND year <= 2100", name="ck_working_year_range"),
    )


# --- PREFERENCES_VERSIONS ----------------------------------------------------
class PreferenceVersion(Base):
    """
    Append-only immutable snapshots (checkpoints).
    Store the full payload as JSON to keep the migration surface small.
    """

    __tablename__ = "preferences_versions"

    # Integer PK (autoincrement), creation order == id order.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    doctor_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("doctors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    month: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="checkpoint", server_default="checkpoint")

    # Full JSON snapshot of the form at save time
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by_role: Mapped[str] = mapped_column(String(16), nullable=False)  # "admin" | "doctor"
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("month >= 1 AND month <= 12", name="ck_versions_month_range"),
        CheckConstraint("year >= 1900 AND year <= 2100", name="ck_versions_year_range"),
    )


# --- PREFERENCES_POINTERS ----------------------------------------------------
class PreferencePointer(Base):
    """
    Single pointer per (doctor_id, year, month) telling which checkpoint is 'current'.
    Denormalized 'submitted_at/by_*' for fast UI reads.
    """

    __tablename__ = "preferences_pointers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    doctor_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("doctors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    month: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # FK do int PK w preferences_versions.id
    current_version_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("preferences_versions.id"), nullable=True
    )

    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    submitted_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    submitted_by_role: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    __table_args__ = (
        UniqueConstraint("doctor_id", "year", "month", name="uq_pointer_doctor_period"),
        CheckConstraint("month >= 1 AND month <= 12", name="ck_pointer_month_range"),
        CheckConstraint("year >= 1900 AND year <= 2100", name="ck_pointer_year_range"),
    )


# --- PREFERENCES_DEADLINES ---------------------------------------------------
class PreferenceDeadline(Base):
    """
    Per-period deadline. Status is computed in service (open/locked), not stored.
    """

    __tablename__ = "preferences_deadlines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    # timezone-aware UTC timestamp
    deadline_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    org_timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Europe/Warsaw", server_default="Europe/Warsaw"
    )

    __table_args__ = (
        UniqueConstraint("year", "month", name="uq_deadline_period"),
        CheckConstraint("month >= 1 AND month <= 12", name="ck_deadline_month_range"),
        CheckConstraint("year >= 1900 AND year <= 2100", name="ck_deadline_year_range"),
    )
