"""add pending_doctors table

Revision ID: 4a1b2c3d4e5f
Revises: ea27576a7619
Create Date: 2025-01-20 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4a1b2c3d4e5f"
down_revision: Union[str, None] = "ea27576a7619"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create pending_doctors table
    op.create_table(
        "pending_doctors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_pending_doctors_email"),
    )
    op.create_index("ix_pending_doctors_email", "pending_doctors", ["email"])


def downgrade() -> None:
    op.drop_index("ix_pending_doctors_email", table_name="pending_doctors")
    op.drop_table("pending_doctors")
