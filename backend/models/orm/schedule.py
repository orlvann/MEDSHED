# backend/models/orm/schedule.py
"""
Schedules ORM models (persistence layer only).

What lives here (DB shape, not business logic):
- Immutable snapshots in `schedule_versions` (payload JSON + labels 'draft'|'published').
- Month-level pointers in `schedule_pointers` pointing to the *current* draft/published version.
- A single autosave buffer per month in `schedule_working`.
- Optional per-version analytics cache in `schedule_diagnostics`:
  * `quality` JSON stores only plain analytics (no datetimes inside JSON),
  * `computed_at` is a DB timestamp column.

What does NOT live here (done in services):
- Creating new versions and moving pointers (generate/checkpoint/publish/revert/redo).
- Overwriting `schedule_working` when the draft pointer moves.
- Counting history and computing undo/redo flags.
- Computing diagnostics and upserting `schedule_diagnostics`.
- Enforcing OCC on working (compare-and-swap on `lock_version`).

Operational notes:
- Version ids are autoincrement PKs; services use them to order history within the same
  (year, month, kind). "Previous" == max(id) < current_id; "Next" == min(id) > current_id.
- We intentionally keep 'kind' as String(+CHECK) to keep migrations easy across SQLite/Postgres.
- All timestamps are timezone-aware (UTC).
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
    """Immutable snapshot for a given {year, month} and 'kind' ('draft' or 'published').

    Service-layer behavior (not here):
    - On generate/checkpoint: insert a new 'draft' version and point the draft pointer to it.
    - On publish: insert a new 'published' version and point the published pointer to it.
    - On draft/published revert/redo: move the respective pointer to the neighbor version.

    The `id` is an autoincrement PK and acts as the ordering key for history within the same
    (year, month, kind). Services use it to find neighbors (prev/next).
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
    """Holds the *current* head per {year, month} for both draft and published.

    Service-layer responsibilities:
    - After inserting a new version, update the respective pointer (draft/published) atomically.
    - On revert/redo, move the pointer to the neighbor version id and (for drafts) overwrite
      `schedule_working` with the pointed payload so the UI reflects the selected state.

    Invariants:
    - At most one pointer row per {year, month}.
    - Pointers store only the *current* head; the full history lives in `schedule_versions`.
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
    """Autosave-only working snapshot per {year, month}.

    Notes:
    - Not a history source; it's the mutable buffer between explicit checkpoints.
    - Optimistic Concurrency Control (OCC) is enforced in services by comparing `lock_version`.
    - Services overwrite this row when the draft pointer moves (revert/redo) to keep UI in sync.
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
    """Optional analytics cache per immutable version (1:1 by `version_id`).

    Conventions:
    - `quality` is plain JSON (numbers/strings/arrays/objects only).
      Do NOT put datetimes inside this JSON; use the `computed_at` column instead.
    - Services upsert this row when (re)computing diagnostics for a version.
    - The 1:1 relation is enforced by a unique constraint on `version_id`.
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
    quality: Mapped[dict] = mapped_column(JSON, nullable=False)  # JSON analytics only (no datetimes inside)

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )  # DB timestamp for when diagnostics were stored/refreshed

    version: Mapped[ScheduleVersion] = relationship("ScheduleVersion")

    def __repr__(self) -> str:
        return f"<ScheduleDiagnostics version_id={self.version_id}>"


__all__ = [
    "ScheduleVersion",
    "SchedulePointer",
    "ScheduleWorking",
    "ScheduleDiagnostics",
]
