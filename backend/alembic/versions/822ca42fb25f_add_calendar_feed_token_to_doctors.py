"""add_calendar_feed_token_to_doctors

Revision ID: 822ca42fb25f
Revises: 4a1b2c3d4e5f
Create Date: 2026-02-22 17:18:15.054692

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "822ca42fb25f"
down_revision: Union[str, Sequence[str], None] = "4a1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("doctors", sa.Column("calendar_feed_token", sa.String(length=36), nullable=True))
    # unique=True on the index enforces uniqueness (SQLite-compatible)
    op.create_index(op.f("ix_doctors_calendar_feed_token"), "doctors", ["calendar_feed_token"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_doctors_calendar_feed_token"), table_name="doctors")
    op.drop_column("doctors", "calendar_feed_token")
