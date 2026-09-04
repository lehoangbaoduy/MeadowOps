"""Chat delivery infrastructure (MEADOWOPS-DOM-014, PRD 6.13/§7/8.4/Appendix
B) — Unit 21a.

New `chat` schema, sibling to live/reporting/engine/sandbox (migration
0001) — PRD §7's second named exception to "no direct cross-subsystem
database access" (the first is the Query Playground's sandbox schema):
`chat_thread`/`chat_message` are a single store both subsystems' own API
layer reads and writes, not either subsystem's own protected schema.

Sandbox-role exclusion: `app.services.sandbox_refresh._live_table_names()`
already filters to `t.schema == "live"` only, so `chat.*` is excluded by
construction with zero code change there. This migration still states the
boundary explicitly, mirroring 0001's own belt-and-suspenders style (its
docstring: "the boundary is visible in the migration, not implicit") rather
than relying on that filter alone — both the schema-level REVOKE and the
ALTER DEFAULT PRIVILEGES line, since 0001's own docstring is explicit that
the *second* line is what protects a table added to the schema later
without anyone remembering to re-run a grant (verified: this is exactly
what makes 0001's own test_a_table_created_later_in_live_schema_is_still_
blocked_by_default true) — matters concretely for this schema's own
documented future addition (attachment storage, out of scope for this
unit).

Immutability (PRD 6.13/ER-6, "no edit, no unsend, by either role"): a
BEFORE UPDATE/DELETE row trigger on chat_message that unconditionally
RAISEs. A plain REVOKE UPDATE/DELETE cannot enforce this — the app's own DB
connection is the `meadowops` schema-owning role (app/services/
sandbox_refresh.py's own docstring: "the only role with DDL on these
schemas"), and Postgres table owners bypass GRANT/REVOKE entirely
regardless of what's revoked from them. A trigger fires for every session
issuing the statement, owner included, so it's the only mechanism here that
actually enforces anything below the API layer — pre-implementation
security review of this unit confirmed this reasoning against the real
grant model before any code was written.

Residual risk, accepted and documented rather than "fixed" (same idiom as
sandbox_refresh.py's own pg_catalog-visibility paragraph): `TRUNCATE`
bypasses row-level (FOR EACH ROW) triggers entirely in Postgres, and
`ALTER TABLE ... DISABLE TRIGGER` then re-enable can suspend row triggers
too. A statement-level `BEFORE TRUNCATE` trigger is added below since that
bypass needs no DDL/owner rights to exploit and costs nothing to close; the
DISABLE-TRIGGER bypass is accepted as-is — it requires the same DDL
privilege as dropping the table outright, no narrower a hole than every
other table in this project already has against its own owning connection.

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERSONAS = (
    "operations_manager",
    "procurement_manager",
    "warehouse_manager",
    "it_manager",
    "operations_director",
    "cfo",
)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS chat")

    # Same deny-by-default posture as migration 0001's live/reporting/engine
    # treatment — stated explicitly, not left to Postgres's own defaults.
    op.execute("REVOKE ALL ON SCHEMA chat FROM PUBLIC")
    op.execute("REVOKE ALL ON SCHEMA chat FROM meadowops_sandbox")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA chat "
        "REVOKE ALL ON TABLES FROM meadowops_sandbox"
    )

    op.create_table(
        "chat_thread",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("scenario_id", sa.UUID(), nullable=False),
        sa.Column(
            "persona",
            sa.Enum(*_PERSONAS, name="stakeholder_persona", schema="chat"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["scenario_id"], ["engine.scenario.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scenario_id", "persona", name="ux_chat_thread_scenario_persona"
        ),
        schema="chat",
    )

    op.create_table(
        "chat_message",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("thread_id", sa.UUID(), nullable=False),
        sa.Column("sender_user_id", sa.UUID(), nullable=False),
        # References the *existing* live.user_role type (migration 0014) -
        # create_type=False, this migration must not try to CREATE TYPE a
        # type that already exists.
        sa.Column(
            "sender_role",
            postgresql.ENUM(
                "admin", "analyst", name="user_role", schema="live", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("attachment_ref", sa.Text(), nullable=True),
        sa.Column(
            "sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["thread_id"], ["chat.chat_thread.id"]),
        sa.ForeignKeyConstraint(["sender_user_id"], ["live.user.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="chat",
    )

    op.execute(
        "CREATE FUNCTION chat.chat_message_immutable() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ "
        "BEGIN "
        "RAISE EXCEPTION "
        "'chat_message rows are immutable (PRD 6.13/ER-6): % is not permitted', TG_OP; "
        "END; $$"
    )
    op.execute(
        "CREATE TRIGGER chat_message_no_update "
        "BEFORE UPDATE ON chat.chat_message "
        "FOR EACH ROW EXECUTE FUNCTION chat.chat_message_immutable()"
    )
    op.execute(
        "CREATE TRIGGER chat_message_no_delete "
        "BEFORE DELETE ON chat.chat_message "
        "FOR EACH ROW EXECUTE FUNCTION chat.chat_message_immutable()"
    )
    op.execute(
        "CREATE TRIGGER chat_message_no_truncate "
        "BEFORE TRUNCATE ON chat.chat_message "
        "FOR EACH STATEMENT EXECUTE FUNCTION chat.chat_message_immutable()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS chat_message_no_truncate ON chat.chat_message")
    op.execute("DROP TRIGGER IF EXISTS chat_message_no_delete ON chat.chat_message")
    op.execute("DROP TRIGGER IF EXISTS chat_message_no_update ON chat.chat_message")
    op.execute("DROP FUNCTION IF EXISTS chat.chat_message_immutable()")
    op.drop_table("chat_message", schema="chat")
    op.drop_table("chat_thread", schema="chat")
    op.execute("DROP TYPE IF EXISTS chat.stakeholder_persona")
    op.execute("DROP SCHEMA IF EXISTS chat CASCADE")
