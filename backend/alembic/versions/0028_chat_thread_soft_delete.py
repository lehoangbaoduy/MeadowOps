"""Soft-delete for chat threads (Unit 37, MEADOWOPS-DOM-025).

The Builder needs to remove a persona thread (e.g. to start a scenario's
conversation over) and have it vanish from every inbox. A hard delete is
impossible by design: chat.chat_message is immutable at the database level
(migration 0018's triggers, PRD 6.13/ER-6) and evaluations/portfolio rows
reference the thread. So a thread gets a nullable `deleted_at`, and every
read path filters on it.

DD-25 (one thread per scenario+persona) used to be a plain UNIQUE
constraint; it becomes a partial unique index over live threads only, so a
deleted thread does not block opening a fresh one for the same pair.

Idempotent on purpose (IF [NOT] EXISTS): production has drifted from
migrations before (0027), and this must be safe to re-run anywhere.

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-01
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE chat.chat_thread ADD COLUMN IF NOT EXISTS deleted_at timestamptz")
    op.execute(
        "ALTER TABLE chat.chat_thread DROP CONSTRAINT IF EXISTS ux_chat_thread_scenario_persona"
    )
    op.execute("DROP INDEX IF EXISTS chat.ux_chat_thread_scenario_persona")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_chat_thread_scenario_persona "
        "ON chat.chat_thread (scenario_id, persona) WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    # Fails if a scenario+persona pair now has more than one thread (a
    # deleted one plus its replacement) - that history cannot be squeezed
    # back under the old plain UNIQUE constraint, and silently dropping
    # threads is not an acceptable "rollback". Likewise refuses outright if
    # any soft-deleted thread exists: dropping deleted_at would silently
    # un-delete it (code review, Unit 37).
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM chat.chat_thread WHERE deleted_at IS NOT NULL) THEN
                RAISE EXCEPTION 'cannot downgrade 0028: soft-deleted chat threads exist';
            END IF;
        END $$
        """
    )
    op.execute("DROP INDEX IF EXISTS chat.ux_chat_thread_scenario_persona")
    op.execute(
        "ALTER TABLE chat.chat_thread ADD CONSTRAINT ux_chat_thread_scenario_persona "
        "UNIQUE (scenario_id, persona)"
    )
    op.execute("ALTER TABLE chat.chat_thread DROP COLUMN IF EXISTS deleted_at")
