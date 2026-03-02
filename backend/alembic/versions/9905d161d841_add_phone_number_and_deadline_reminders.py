"""add_phone_number_and_deadline_reminders

Revision ID: 9905d161d841
Revises: 822ca42fb25f
Create Date: 2026-02-22 20:57:36.766560

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9905d161d841"
down_revision: Union[str, Sequence[str], None] = "822ca42fb25f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # New table: deadline_reminders_sent
    op.create_table(
        "deadline_reminders_sent",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("deadline_id", sa.Integer(), nullable=False),
        sa.Column("reminder_type", sa.String(length=10), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deadline_id", "reminder_type", name="uq_deadline_reminder"),
    )
    op.create_index(
        op.f("ix_deadline_reminders_sent_deadline_id"), "deadline_reminders_sent", ["deadline_id"], unique=False
    )

    # Add phone_number to doctors and pending_doctors
    op.add_column("doctors", sa.Column("phone_number", sa.String(length=20), nullable=True))
    op.add_column("pending_doctors", sa.Column("phone_number", sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("pending_doctors", "phone_number")
    op.drop_column("doctors", "phone_number")
    op.drop_index(op.f("ix_deadline_reminders_sent_deadline_id"), table_name="deadline_reminders_sent")
    op.drop_table("deadline_reminders_sent")
