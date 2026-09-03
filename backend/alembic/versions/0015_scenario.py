"""Scenario builder controls (MEADOWOPS-DOM-011, business id
MEADOWOPS-DOMAIN-009, PRD 6.4, DD-24).

Adds `scenario` to the `engine` schema — that schema already exists and is
already access-controlled (0001_create_schemas_and_sandbox_role.py: same
CREATE SCHEMA / REVOKE ALL treatment as `live`/`reporting`), provisioned
since Migration 0001 specifically for "scenario, evaluation, portfolio" and
never used until now (DD-24 point 1). This migration needs no CREATE
SCHEMA or REVOKE/GRANT statements of its own.

Every new enum type here is created in `engine`, not `live` — app.db.base's
pg_enum grew an optional `schema` kwarg (default "live", unchanged for
every existing caller) specifically for this unit, so a type lives
alongside its own table rather than defaulting to `live` regardless of
where the table actually is (same autogenerate/downgrade symmetry
reasoning pg_enum's own docstring already gives).

`source_exception_flag_id` is a plain UUID column, deliberately not a
ForeignKeyConstraint to live.exception_flag.id (app/db/scenario.py's class
docstring has the full reasoning: it is a soft/provenance reference, same
pattern as app.db.ledger.DecisionEvent.scenario_id).

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scenario",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column(
            "scenario_type",
            sa.Enum(
                "stakeholder_request",
                "data_quality_issue",
                "root_cause_investigation",
                "supplier_vendor_decision",
                "process_breakdown",
                "executive_reporting",
                name="scenario_type",
                schema="engine",
            ),
            nullable=False,
        ),
        sa.Column(
            "competency_cluster",
            sa.Enum(
                "analysis_diagnosis",
                "judgment_delivery",
                "communication",
                name="competency_cluster",
                schema="engine",
            ),
            nullable=False,
        ),
        sa.Column(
            "difficulty_tier",
            sa.Enum(
                "foundational",
                "standard",
                "stretch",
                name="difficulty_tier",
                schema="engine",
            ),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum("exception_flag", "manual", name="scenario_source", schema="engine"),
            nullable=False,
        ),
        sa.Column("source_exception_flag_id", sa.UUID(), nullable=True),
        sa.Column("ground_truth", postgresql.JSONB(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "draft", "approved", "active", "cancelled", name="scenario_status", schema="engine"
            ),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["created_by"], ["live.user.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="engine",
    )


def downgrade() -> None:
    op.drop_table("scenario", schema="engine")
    op.execute("DROP TYPE IF EXISTS engine.scenario_status")
    op.execute("DROP TYPE IF EXISTS engine.scenario_source")
    op.execute("DROP TYPE IF EXISTS engine.difficulty_tier")
    op.execute("DROP TYPE IF EXISTS engine.competency_cluster")
    op.execute("DROP TYPE IF EXISTS engine.scenario_type")
