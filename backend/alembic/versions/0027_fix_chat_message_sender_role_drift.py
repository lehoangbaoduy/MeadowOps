"""Repair production schema drift (B14): chat.chat_message is missing its
sender_role column on the live Railway/Neon database, even though alembic
believes revision 0018 (which creates this table with sender_role already
included, see that file) is fully applied there.

Discovered from a live user bug report: every real send_message/
list_messages call against production 500'd with psycopg.errors.
UndefinedColumn: column "sender_role" of relation "chat_message" does not
exist (confirmed via Railway logs and a direct information_schema query -
production's chat_message table has only 6 of its 7 mapped columns: id,
thread_id, sender_user_id, body, attachment_ref, sent_at).

Best explanation: an earlier deploy ran `alembic upgrade head` against
production while migration 0018's own file locally still lacked this
column (added in a later, pre-commit edit) - alembic then stamped 0018 as
applied and has had no reason to revisit it since, so `alembic upgrade
head` alone does not fix this on production (it already reports 0026,
head). Every other environment (local dev, CI) built chat_message from
0018's *current* content, which already includes sender_role - this
migration must be a no-op there. `IF NOT EXISTS`/idempotent ALTERs make it
safe everywhere, not just on the one drifted database it's meant to
repair. chat_message is confirmed empty on production (every INSERT has
been failing at the DB level since this column never existed), so adding
it NOT NULL with no default and no backfill is safe.

See tests/data/test_chat_schema.py::
test_migration_0027_repairs_a_missing_sender_role_column for the regression
test, which executes this file's own upgrade() function directly.

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-15
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE chat.chat_message ADD COLUMN IF NOT EXISTS sender_role live.user_role"
    )
    op.execute("ALTER TABLE chat.chat_message ALTER COLUMN sender_role SET NOT NULL")


def downgrade() -> None:
    # Matches this migration's own repair-only scope - not a real rollback
    # of 0018, which never dropped sender_role in the first place anywhere
    # except the one drifted database this exists to fix.
    op.execute("ALTER TABLE chat.chat_message DROP COLUMN IF EXISTS sender_role")
