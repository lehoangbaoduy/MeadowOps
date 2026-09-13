"""Unit 30b (MEADOWOPS-UI-004, PRD 6.1 'Drafting' bullet, catalog row 31,
B12 follow-on to U30): a per-(thread, user) draft table.

`chat.chat_thread_draft` mirrors migration 0019's `chat_thread_read_state`
exactly in shape (composite (thread_id, user_id) primary key, ordinary
mutable table, same `chat` schema) — see app.db.chat.ChatThreadDraft's own
docstring for why this is its own table rather than a column folded into
either ChatThread or chat_thread_read_state.

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_thread_draft",
        sa.Column("thread_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["chat.chat_thread.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["live.user.id"]),
        sa.PrimaryKeyConstraint("thread_id", "user_id"),
        schema="chat",
    )


def downgrade() -> None:
    op.drop_table("chat_thread_draft", schema="chat")
