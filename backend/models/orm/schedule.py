# schedule tables
"""
Schedules ORM models.

Design highlights (service-layer responsibilities marked as TODO in comments):
- Immutable versions + (draft|published) label stored in `schedule_versions` table.
- Pointers table holds the *current* draft/published version_id for each {year,month}.
- Working table stores the last autosaved "work-in-progress" snapshot for UI.
- History is created *only* from explicit generate/save (create checkpoint)/publish actions.
- UTC timestamps (timezone=True); DB servers are expected to run in UTC.

Kinds policy:
- We intentionally avoid a hard DB ENUM for 'kind' to keep migrations simple
  across SQLite (dev) and Postgres (prod). Instead, we use a String + CHECK.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.session import Base

KindLiteral = Literal["draft", "published"]


class ScheduleVersion(Base):
    """Immutable snapshot of a schedule for a given {year, month}.

    Each explicit operation (generate/save (create checkpoint)/publish) must create
    a new row here. The 'kind' is only a *label* of the saved version,
    not an indicator of "currentness".
    """

    __tablename__ = "schedule_versions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Month scope
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)

    # Full schedule payload (assignments + meta). Immutable by convention.
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    # Version label: "draft" or "published" (not a DB ENUM on purpose).
    kind: Mapped[str] = mapped_column(String(16), nullable=False)

    # Audit: creator + role label (string to avoid hard-coupling to ENUMs).
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_role: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships (lazy by default; we don't backref from User to avoid noise)
    # user = relationship("User")  # optional to enable later if needed

    __table_args__ = (
        # Practical lookups
        Index("ix_schedule_versions_year_month", "year", "month"),
        Index("ix_schedule_versions_year_month_kind", "year", "month", "kind"),
        # Keep the label constrained without hard DB ENUM.
        CheckConstraint(
            "kind in ('draft','published')",
            name="ck_schedule_versions_kind",
        ),
    )

    def __repr__(self) -> str:
        return f"<ScheduleVersion id={self.id} {self.year}-{self.month:02d} " f"kind={self.kind}>"


class SchedulePointer(Base):
    """Holds *current* pointers per {year,month} for draft and published.

    Only one current draft and one current published per (year, month).
    Service layer must update these pointers atomically when publishing
    or moving draft head.

    TODO(service): On publish:
      - insert new ScheduleVersion(kind='published')
      - set pointer.current_published_version_id to that id
      - optionally copy the version payload to working for UI refresh

    TODO(service): On "set current draft" (generate/save):
      - insert new ScheduleVersion(kind='draft')
      - move pointer.current_draft_version_id to that id
      - also update working snapshot for immediate UI
    """

    __tablename__ = "schedule_pointers"

    # Composite PK enforces uniqueness of the month scope.
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    month: Mapped[int] = mapped_column(Integer, primary_key=True)

    current_draft_version_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("schedule_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    current_published_version_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("schedule_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Optional relationships for convenience (no cascade deletes).
    current_draft_version: Mapped[Optional[ScheduleVersion]] = relationship(
        "ScheduleVersion",
        foreign_keys=[current_draft_version_id],
    )
    current_published_version: Mapped[Optional[ScheduleVersion]] = relationship(
        "ScheduleVersion",
        foreign_keys=[current_published_version_id],
    )

    def __repr__(self) -> str:
        return (
            f"<SchedulePointer {self.year}-{self.month:02d} "
            f"draft={self.current_draft_version_id} "
            f"published={self.current_published_version_id}>"
        )


class ScheduleWorking(Base):
    """Autosave-only working snapshot per {year,month}.

    This table is NOT a history source. It's only the latest "working copy"
    feeding the UI between explicit checkpoints.

    Concurrency:
    - Optional `lock_version` (int) supports optimistic concurrency control
      on the service layer (compare-and-swap on update).
    """

    __tablename__ = "schedule_working"

    # Composite PK: at most one working snapshot per {year,month}.
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    month: Mapped[int] = mapped_column(Integer, primary_key=True)

    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    updated_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # updated_by_user = relationship("User")  # optional to enable later

    __table_args__ = (
        # Extra uniqueness is redundant due to PK, but kept as documentation.
        UniqueConstraint("year", "month", name="uq_schedule_working_year_month"),
    )

    def __repr__(self) -> str:
        return f"<ScheduleWorking {self.year}-{self.month:02d} " f"lock_version={self.lock_version}>"


class ScheduleDiagnostics(Base):
    """Optional diagnostics per immutable version.

    One row per version_id with computed quality metrics.
    This table is safe to introduce now; services may start writing to it later.
    """

    __tablename__ = "schedule_diagnostics"

    # 1:1 with version (enforced by unique FK or PK-on-FK strategy)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    version_id: Mapped[int] = mapped_column(
        ForeignKey("schedule_versions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # enforce 1:1
        index=True,
    )

    # Arbitrary metrics (penalties, coverage, fairness, etc.)
    quality: Mapped[dict] = mapped_column(JSON, nullable=False)

    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    version: Mapped[ScheduleVersion] = relationship("ScheduleVersion")

    def __repr__(self) -> str:
        return f"<ScheduleDiagnostics version_id={self.version_id}>"


__all__ = [
    "ScheduleVersion",
    "SchedulePointer",
    "ScheduleWorking",
    "ScheduleDiagnostics",
]
