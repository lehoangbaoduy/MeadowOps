"""Human review workflow mechanism + portfolio artifact (MEADOWOPS-DOM-020,
PRD 6.6 step 11, ER-1 through ER-6, 6.10) - Unit 26.

`engine.human_review` attaches a monthly reviewer's verdict to an existing
`engine.evaluation` row without ever mutating that row (ER-1) - same
immutability-trigger shape as migration 0020's `engine.evaluation`, plus a
CHECK constraint pairing `verdict`/`overridden_recommendation` (edge case
#29). `overridden_recommendation` reuses `engine.difficulty_recommendation`
(migration 0020) rather than creating a second enum type -
`create_type=False` on this second reference, or CREATE TYPE would fail
against a type that already exists.

`engine.portfolio_artifact` holds only the Analyst's seven-question
reflection (app.db.portfolio's own docstring explains why the rest of PRD
6.10's "artifact" is compiled on demand, not stored here) - same
immutability-trigger shape again.

Both tables carry a `submitted_by_user_id` FK to `live.user.id` (security
review of this unit) - the authenticated identity that operated the write
route, populated from `identity["user_id"]` there. See each table's own
docstring (app.db.human_review, app.db.portfolio) for how this differs from
`human_review.reviewer_name`.

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_HUMAN_REVIEW_VERDICTS = ("agree", "override")
_DIFFICULTY_RECOMMENDATIONS = ("foundational", "standard", "stretch", "hold")


def upgrade() -> None:
    op.create_table(
        "human_review",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("evaluation_id", sa.UUID(), nullable=False),
        sa.Column("submitted_by_user_id", sa.UUID(), nullable=False),
        sa.Column("reviewer_name", sa.Text(), nullable=False),
        sa.Column(
            "verdict",
            sa.Enum(
                *_HUMAN_REVIEW_VERDICTS, name="human_review_verdict", schema="engine"
            ),
            nullable=False,
        ),
        sa.Column("tier_assessment_notes", sa.Text(), nullable=False),
        sa.Column(
            "overridden_recommendation",
            # postgresql.ENUM, not plain sa.Enum - only the dialect-specific
            # class actually honors create_type (verified against this
            # SQLAlchemy version: sa.Enum(..., create_type=False) silently
            # drops the kwarg, and CREATE TABLE then tries to re-CREATE TYPE
            # engine.difficulty_recommendation, which migration 0020 already
            # created - DuplicateObject).
            postgresql.ENUM(
                *_DIFFICULTY_RECOMMENDATIONS,
                name="difficulty_recommendation",
                schema="engine",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["evaluation_id"], ["engine.evaluation.id"]),
        sa.ForeignKeyConstraint(["submitted_by_user_id"], ["live.user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evaluation_id", name="ux_human_review_evaluation_id"),
        sa.CheckConstraint(
            "(verdict = 'agree' AND overridden_recommendation IS NULL) OR "
            "(verdict = 'override' AND overridden_recommendation IS NOT NULL)",
            name="ck_human_review_verdict_recommendation_pairing",
        ),
        schema="engine",
    )
    op.execute(
        "CREATE FUNCTION engine.human_review_immutable() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ "
        "BEGIN "
        "RAISE EXCEPTION "
        "'human_review rows are immutable (PRD 6.9 ER-3/ER-6): % is not permitted', TG_OP; "
        "END; $$"
    )
    op.execute(
        "CREATE TRIGGER human_review_no_update "
        "BEFORE UPDATE ON engine.human_review "
        "FOR EACH ROW EXECUTE FUNCTION engine.human_review_immutable()"
    )
    op.execute(
        "CREATE TRIGGER human_review_no_delete "
        "BEFORE DELETE ON engine.human_review "
        "FOR EACH ROW EXECUTE FUNCTION engine.human_review_immutable()"
    )
    op.execute(
        "CREATE TRIGGER human_review_no_truncate "
        "BEFORE TRUNCATE ON engine.human_review "
        "FOR EACH STATEMENT EXECUTE FUNCTION engine.human_review_immutable()"
    )

    op.create_table(
        "portfolio_artifact",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("thread_id", sa.UUID(), nullable=False),
        sa.Column("submitted_by_user_id", sa.UUID(), nullable=False),
        sa.Column("reflection_what_happened", sa.Text(), nullable=False),
        sa.Column("reflection_initial_thought", sa.Text(), nullable=False),
        sa.Column("reflection_evidence_that_mattered", sa.Text(), nullable=False),
        sa.Column("reflection_what_missed", sa.Text(), nullable=False),
        sa.Column("reflection_what_changed_after_pushback", sa.Text(), nullable=False),
        sa.Column("reflection_what_differently", sa.Text(), nullable=False),
        sa.Column("reflection_skill_improved", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["thread_id"], ["chat.chat_thread.id"]),
        sa.ForeignKeyConstraint(["submitted_by_user_id"], ["live.user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("thread_id", name="ux_portfolio_artifact_thread_id"),
        schema="engine",
    )
    op.execute(
        "CREATE FUNCTION engine.portfolio_artifact_immutable() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ "
        "BEGIN "
        "RAISE EXCEPTION "
        "'portfolio_artifact rows are immutable (PRD 6.10): % is not permitted', TG_OP; "
        "END; $$"
    )
    op.execute(
        "CREATE TRIGGER portfolio_artifact_no_update "
        "BEFORE UPDATE ON engine.portfolio_artifact "
        "FOR EACH ROW EXECUTE FUNCTION engine.portfolio_artifact_immutable()"
    )
    op.execute(
        "CREATE TRIGGER portfolio_artifact_no_delete "
        "BEFORE DELETE ON engine.portfolio_artifact "
        "FOR EACH ROW EXECUTE FUNCTION engine.portfolio_artifact_immutable()"
    )
    op.execute(
        "CREATE TRIGGER portfolio_artifact_no_truncate "
        "BEFORE TRUNCATE ON engine.portfolio_artifact "
        "FOR EACH STATEMENT EXECUTE FUNCTION engine.portfolio_artifact_immutable()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS portfolio_artifact_no_truncate ON engine.portfolio_artifact")
    op.execute("DROP TRIGGER IF EXISTS portfolio_artifact_no_delete ON engine.portfolio_artifact")
    op.execute("DROP TRIGGER IF EXISTS portfolio_artifact_no_update ON engine.portfolio_artifact")
    op.execute("DROP FUNCTION IF EXISTS engine.portfolio_artifact_immutable()")
    op.drop_table("portfolio_artifact", schema="engine")

    op.execute("DROP TRIGGER IF EXISTS human_review_no_truncate ON engine.human_review")
    op.execute("DROP TRIGGER IF EXISTS human_review_no_delete ON engine.human_review")
    op.execute("DROP TRIGGER IF EXISTS human_review_no_update ON engine.human_review")
    op.execute("DROP FUNCTION IF EXISTS engine.human_review_immutable()")
    op.drop_table("human_review", schema="engine")
    op.execute("DROP TYPE IF EXISTS engine.human_review_verdict")
