"""schedules: versions/pointers/working/diagnostics

Revision ID: 29cd79341184
Revises: f07e81483ae2
Create Date: 2025-11-02 16:09:49.529850

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "29cd79341184"
down_revision: Union[str, Sequence[str], None] = "f07e81483ae2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- schedule_versions ---
    op.create_table(
        "schedule_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by_role", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("kind in ('draft','published')", name="ck_schedule_versions_kind"),
    )
    op.create_index(
        "ix_schedule_versions_year_month",
        "schedule_versions",
        ["year", "month"],
        unique=False,
    )
    op.create_index(
        "ix_schedule_versions_year_month_kind",
        "schedule_versions",
        ["year", "month", "kind"],
        unique=False,
    )

    # --- schedule_pointers ---
    op.create_table(
        "schedule_pointers",
        sa.Column("year", sa.Integer(), primary_key=True),
        sa.Column("month", sa.Integer(), primary_key=True),
        sa.Column(
            "current_draft_version_id",
            sa.Integer(),
            sa.ForeignKey("schedule_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "current_published_version_id",
            sa.Integer(),
            sa.ForeignKey("schedule_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_schedule_pointers_current_draft_version_id",
        "schedule_pointers",
        ["current_draft_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_schedule_pointers_current_published_version_id",
        "schedule_pointers",
        ["current_published_version_id"],
        unique=False,
    )

    # --- schedule_working ---
    op.create_table(
        "schedule_working",
        sa.Column("year", sa.Integer(), primary_key=True),
        sa.Column("month", sa.Integer(), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("lock_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "updated_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("year", "month", name="uq_schedule_working_year_month"),
    )

    # --- schedule_diagnostics (opcjonalnie; można zostawić) ---
    op.create_table(
        "schedule_diagnostics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "version_id",
            sa.Integer(),
            sa.ForeignKey("schedule_versions.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("quality", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_schedule_diagnostics_version_id",
        "schedule_diagnostics",
        ["version_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_schedule_diagnostics_version_id", table_name="schedule_diagnostics")
    op.drop_table("schedule_diagnostics")

    op.drop_table("schedule_working")

    op.drop_index("ix_schedule_pointers_current_published_version_id", table_name="schedule_pointers")
    op.drop_index("ix_schedule_pointers_current_draft_version_id", table_name="schedule_pointers")
    op.drop_table("schedule_pointers")

    op.drop_index("ix_schedule_versions_year_month_kind", table_name="schedule_versions")
    op.drop_index("ix_schedule_versions_year_month", table_name="schedule_versions")
    op.drop_table("schedule_versions")
