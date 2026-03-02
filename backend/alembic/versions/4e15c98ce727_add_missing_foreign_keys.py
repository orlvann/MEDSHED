"""add missing foreign keys

Revision ID: 4e15c98ce727
Revises: 9905d161d841
Create Date: 2026-03-01 22:09:04.750434

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4e15c98ce727"
down_revision: Union[str, Sequence[str], None] = "9905d161d841"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # SQLite cannot reliably "ALTER TABLE ... ADD CONSTRAINT".
    # Alembic batch mode recreates the table and copies data,
    # so the same migration works on SQLite (dev) and Postgres (prod).

    # FK: preferences_working.doctor_id -> doctors.id
    with op.batch_alter_table("preferences_working", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_preferences_working_doctor_id_doctors",
            "doctors",
            ["doctor_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # FK: preferences_versions.doctor_id -> doctors.id
    with op.batch_alter_table("preferences_versions", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_preferences_versions_doctor_id_doctors",
            "doctors",
            ["doctor_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # FK: preferences_pointers.doctor_id -> doctors.id
    with op.batch_alter_table("preferences_pointers", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_preferences_pointers_doctor_id_doctors",
            "doctors",
            ["doctor_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # FK: deadline_reminders_sent.deadline_id -> preferences_deadlines.id
    with op.batch_alter_table("deadline_reminders_sent", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_deadline_reminders_sent_deadline_id_preferences_deadlines",
            "preferences_deadlines",
            ["deadline_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop in reverse order
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
