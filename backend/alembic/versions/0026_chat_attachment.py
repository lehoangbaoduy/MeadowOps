"""Unit 30c (MEADOWOPS-UI-005, S1-FR-15/PRD 347/380, B12 follow-on to U30):
attachment metadata for the Analyst-side file-attachment feature.

`chat.chat_attachment` stores metadata only (filename/content-type/size/
storage key) - the file bytes themselves live in the filesystem-backed
object store (app.core.storage), never in this table or any other Postgres
column, per PRD 380's explicit "object storage... never in the operational
Postgres database."

`message_id` is nullable and UNIQUE (Postgres allows multiple NULLs under a
plain UNIQUE constraint) rather than a required FK set at row-creation time,
because of a real ordering constraint: `chat.chat_message` has migration
0018's BEFORE UPDATE/DELETE/TRUNCATE immutability trigger, so a ChatMessage
row's attachment_ref must be set once, at INSERT - there is no later UPDATE
to attach a file to an already-sent message. The upload therefore happens
first (creating this row with message_id=NULL), and app.services.chat.
send_message "claims" it by setting message_id in the same transaction as
the ChatMessage insert.

Comment correction (dual review, this unit): an earlier version of this
docstring described the UNIQUE constraint on message_id as "the DB-level
half" of "an uploaded attachment can back at most one message." Both
reviewers traced that this doesn't actually engage for the race it was
meant to guard against - two concurrent claims of the *same* attachment_id
write two different message_id values to that one row (an ordinary
last-writer-wins UPDATE), never a cross-row uniqueness conflict. What
actually holds the invariant is send_message's `with_for_update=True` row
lock on the attachment row, taken before the already-claimed check runs -
the UNIQUE constraint here is a data-shape guarantee (one message_id value
is never shared by two attachment rows), not a concurrency control.

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_attachment",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("thread_id", sa.UUID(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.UUID(), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["thread_id"], ["chat.chat_thread.id"]),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["live.user.id"]),
        sa.ForeignKeyConstraint(["message_id"], ["chat.chat_message.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", name="uq_chat_attachment_message_id"),
        schema="chat",
    )


def downgrade() -> None:
    op.drop_table("chat_attachment", schema="chat")
