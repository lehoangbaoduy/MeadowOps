"""Chat thread read-state (MEADOWOPS-DOM-015, PRD S1-FR-15) — Unit 21.

Unread-thread badges need per-(thread, user) "last read" state. Deliberately
a separate, ordinary mutable table rather than a column on `chat_message`
itself — that table is immutability-trigger-protected (migration 0018,
PRD 6.13/ER-6, "no edit, no unsend, by either role"), and read-state is by
definition something that changes constantly as a user reads new messages,
the opposite of what that trigger exists to prevent.

Lives in the existing `chat` schema, not a new one — no additional
schema-level REVOKE/ALTER DEFAULT PRIVILEGES statements needed here.
Migration 0018 already REVOKEs `meadowops_sandbox` at the schema level and
sets `ALTER DEFAULT PRIVILEGES IN SCHEMA chat ... FROM meadowops_sandbox`,
which (per its own docstring, and proven by 0018's own
`test_a_table_created_later_in_chat_schema_is_still_blocked_by_default`)
covers every table added to `chat` afterward, this one included.

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_thread_read_state",
        sa.Column("thread_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["chat.chat_thread.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["live.user.id"]),
        sa.PrimaryKeyConstraint("thread_id", "user_id"),
        schema="chat",
    )


def downgrade() -> None:
    op.drop_table("chat_thread_read_state", schema="chat")
