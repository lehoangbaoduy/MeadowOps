"""AI evaluation framework + ChatThread.status (MEADOWOPS-DOM-019, PRD
6.6 steps 8-9, 6.8) - Unit 25.

`engine.evaluation` mirrors `engine.scenario` (migration 0015) - same
schema, same immutability-trigger shape as `chat.chat_message` (migration
0018's own docstring has the full reasoning: table-owner connections
bypass GRANT/REVOKE, so only a BEFORE UPDATE/DELETE/TRUNCATE trigger
actually enforces ER-6's "never silently rewritten" here).

`chat.chat_thread_status` is a new enum type in the existing `chat` schema
(migration 0018) - `create_type=True` (default) since this is the first
migration to reference it.

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_THREAD_STATUSES = ("open", "completed")
_DIFFICULTY_RECOMMENDATIONS = ("foundational", "standard", "stretch", "hold")


def upgrade() -> None:
    # op.add_column (unlike op.create_table) does not auto-CREATE TYPE for
    # an inline sa.Enum - the type must exist before ALTER TABLE ... ADD
    # COLUMN references it.
    thread_status_type = sa.Enum(
        *_THREAD_STATUSES, name="chat_thread_status", schema="chat"
    )
    thread_status_type.create(op.get_bind())
    op.add_column(
        "chat_thread",
        sa.Column(
            "status",
            thread_status_type,
            nullable=False,
            server_default="open",
        ),
        schema="chat",
    )

    op.create_table(
        "evaluation",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("thread_id", sa.UUID(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("strengths", sa.Text(), nullable=False),
        sa.Column("gaps", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("senior_analyst_pushback", sa.Text(), nullable=False),
        sa.Column("final_verdict", sa.Text(), nullable=False),
        sa.Column("suggested_next_skill_focus", sa.Text(), nullable=False),
        sa.Column(
            "difficulty_recommendation",
            sa.Enum(
                *_DIFFICULTY_RECOMMENDATIONS,
                name="difficulty_recommendation",
                schema="engine",
            ),
            nullable=False,
        ),
        sa.Column("raw_response", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["thread_id"], ["chat.chat_thread.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("thread_id", name="ux_evaluation_thread_id"),
        schema="engine",
    )

    op.execute(
        "CREATE FUNCTION engine.evaluation_immutable() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ "
        "BEGIN "
        "RAISE EXCEPTION "
        "'evaluation rows are immutable (PRD 6.9 ER-6): % is not permitted', TG_OP; "
        "END; $$"
    )
    op.execute(
        "CREATE TRIGGER evaluation_no_update "
        "BEFORE UPDATE ON engine.evaluation "
        "FOR EACH ROW EXECUTE FUNCTION engine.evaluation_immutable()"
    )
    op.execute(
        "CREATE TRIGGER evaluation_no_delete "
        "BEFORE DELETE ON engine.evaluation "
        "FOR EACH ROW EXECUTE FUNCTION engine.evaluation_immutable()"
    )
    op.execute(
        "CREATE TRIGGER evaluation_no_truncate "
        "BEFORE TRUNCATE ON engine.evaluation "
        "FOR EACH STATEMENT EXECUTE FUNCTION engine.evaluation_immutable()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS evaluation_no_truncate ON engine.evaluation")
    op.execute("DROP TRIGGER IF EXISTS evaluation_no_delete ON engine.evaluation")
    op.execute("DROP TRIGGER IF EXISTS evaluation_no_update ON engine.evaluation")
    op.execute("DROP FUNCTION IF EXISTS engine.evaluation_immutable()")
    op.drop_table("evaluation", schema="engine")
    op.execute("DROP TYPE IF EXISTS engine.difficulty_recommendation")
    op.drop_column("chat_thread", "status", schema="chat")
    op.execute("DROP TYPE IF EXISTS chat.chat_thread_status")
