"""add missing foreign keys

Revision ID: 4e15c98ce727
Revises: 9905d161d841
Create Date: 2026-03-01 22:09:04.750434

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4e15c98ce727"
down_revision: Union[str, Sequence[str], None] = "9905d161d841"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    """Upgrade schema."""

    if _is_sqlite():
        # SQLite needs batch mode (recreate) to add FK constraints.
        with op.batch_alter_table("preferences_working", recreate="always") as batch:
            batch.create_foreign_key(
                "fk_preferences_working_doctor_id_doctors",
                "doctors", ["doctor_id"], ["id"], ondelete="CASCADE",
            )
        with op.batch_alter_table("preferences_versions", recreate="always") as batch:
            batch.create_foreign_key(
                "fk_preferences_versions_doctor_id_doctors",
                "doctors", ["doctor_id"], ["id"], ondelete="CASCADE",
            )
        with op.batch_alter_table("preferences_pointers", recreate="always") as batch:
            batch.create_foreign_key(
                "fk_preferences_pointers_doctor_id_doctors",
                "doctors", ["doctor_id"], ["id"], ondelete="CASCADE",
            )
        with op.batch_alter_table("deadline_reminders_sent", recreate="always") as batch:
            batch.create_foreign_key(
                "fk_deadline_reminders_sent_deadline_id_preferences_deadlines",
                "preferences_deadlines", ["deadline_id"], ["id"], ondelete="CASCADE",
            )
    else:
        # PostgreSQL: clean up orphaned rows before adding FK constraints.
        # Order matters: pointers references versions, so clean child tables first.
        conn = op.get_bind()
        conn.execute(sa.text(
            "DELETE FROM preferences_pointers "
            "WHERE doctor_id NOT IN (SELECT id FROM doctors)"
        ))
        conn.execute(sa.text(
            "DELETE FROM preferences_versions "
            "WHERE doctor_id NOT IN (SELECT id FROM doctors)"
        ))
        conn.execute(sa.text(
            "DELETE FROM preferences_working "
            "WHERE doctor_id NOT IN (SELECT id FROM doctors)"
        ))
        conn.execute(sa.text(
            "DELETE FROM deadline_reminders_sent "
            "WHERE deadline_id NOT IN (SELECT id FROM preferences_deadlines)"
        ))

        # PostgreSQL supports ALTER TABLE ADD CONSTRAINT directly.
        op.create_foreign_key(
            "fk_preferences_working_doctor_id_doctors",
            "preferences_working", "doctors",
            ["doctor_id"], ["id"], ondelete="CASCADE",
        )
        op.create_foreign_key(
            "fk_preferences_versions_doctor_id_doctors",
            "preferences_versions", "doctors",
            ["doctor_id"], ["id"], ondelete="CASCADE",
        )
        op.create_foreign_key(
            "fk_preferences_pointers_doctor_id_doctors",
            "preferences_pointers", "doctors",
            ["doctor_id"], ["id"], ondelete="CASCADE",
        )
        op.create_foreign_key(
            "fk_deadline_reminders_sent_deadline_id_preferences_deadlines",
            "deadline_reminders_sent", "preferences_deadlines",
            ["deadline_id"], ["id"], ondelete="CASCADE",
        )


def downgrade() -> None:
    """Downgrade schema."""
    if _is_sqlite():
        with op.batch_alter_table("deadline_reminders_sent", recreate="always") as batch:
            batch.drop_constraint(
                "fk_deadline_reminders_sent_deadline_id_preferences_deadlines",
                type_="foreignkey",
            )
        with op.batch_alter_table("preferences_pointers", recreate="always") as batch:
            batch.drop_constraint(
                "fk_preferences_pointers_doctor_id_doctors",
                type_="foreignkey",
            )
        with op.batch_alter_table("preferences_versions", recreate="always") as batch:
            batch.drop_constraint(
                "fk_preferences_versions_doctor_id_doctors",
                type_="foreignkey",
            )
        with op.batch_alter_table("preferences_working", recreate="always") as batch:
            batch.drop_constraint(
                "fk_preferences_working_doctor_id_doctors",
                type_="foreignkey",
            )
    else:
        op.drop_constraint("fk_deadline_reminders_sent_deadline_id_preferences_deadlines", "deadline_reminders_sent", type_="foreignkey")
        op.drop_constraint("fk_preferences_pointers_doctor_id_doctors", "preferences_pointers", type_="foreignkey")
        op.drop_constraint("fk_preferences_versions_doctor_id_doctors", "preferences_versions", type_="foreignkey")
        op.drop_constraint("fk_preferences_working_doctor_id_doctors", "preferences_working", type_="foreignkey")
