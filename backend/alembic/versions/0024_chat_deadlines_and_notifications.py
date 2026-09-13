"""Unit 30a (MEADOWOPS-UI-003, PRD 6.1/6.13, B12 follow-on to U30): chat
thread deadline tracking + a new Notification model.

`chat_thread` gets three new columns: `deadline_at` (set/cleared by
app.services.chat.send_message on every message), and the
`deadline_approaching_notified`/`overdue_notified` idempotency pair that
makes catalog row 30's "no double-fires across scheduler downtime"
provable (app.services.notifications.sweep_thread_deadlines only ever
writes each notification kind once per deadline_at). Deliberately NOT a
ChatThreadStatus expansion - see that enum's own docstring
(app.db.enums).

`chat.notification` is a new, ordinary mutable table (no ER-6 immutability
trigger, matching chat_thread_read_state's own precedent, migration 0019)
- see app.db.chat.Notification's own docstring for why only two of PRD
6.1's four named notification kinds are modeled here.

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOTIFICATION_KINDS = ("deadline_approaching", "deadline_missed")


def upgrade() -> None:
    op.add_column(
        "chat_thread",
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        schema="chat",
    )
    op.add_column(
        "chat_thread",
        sa.Column(
            "deadline_approaching_notified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="chat",
    )
    op.add_column(
        "chat_thread",
        sa.Column(
            "overdue_notified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="chat",
    )

    # op.create_table auto-CREATEs an inline sa.Enum's type (unlike
    # op.add_column, migration 0020's own docstring), so no separate
    # .create(op.get_bind()) call is needed here.
    notification_kind_type = sa.Enum(
        *_NOTIFICATION_KINDS, name="notification_kind", schema="chat"
    )
    op.create_table(
        "notification",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("thread_id", sa.UUID(), nullable=False),
        sa.Column("kind", notification_kind_type, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["live.user.id"]),
        sa.ForeignKeyConstraint(["thread_id"], ["chat.chat_thread.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="chat",
    )
    # Backs both list_notifications_for_user's ORDER BY created_at DESC and
    # mark_notification_read's (id, user_id) ownership-scoped lookup - a
    # btree on (user_id, created_at) supports a backward scan for DESC
    # without a second index.
    op.create_index(
        "ix_notification_user_created",
        "notification",
        ["user_id", "created_at"],
        schema="chat",
    )


def downgrade() -> None:
    op.drop_index("ix_notification_user_created", table_name="notification", schema="chat")
    op.drop_table("notification", schema="chat")
    op.execute("DROP TYPE IF EXISTS chat.notification_kind")
    op.drop_column("chat_thread", "overdue_notified", schema="chat")
    op.drop_column("chat_thread", "deadline_approaching_notified", schema="chat")
    op.drop_column("chat_thread", "deadline_at", schema="chat")
