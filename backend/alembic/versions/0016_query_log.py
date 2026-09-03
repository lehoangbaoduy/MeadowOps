"""Query Playground execution logging (MEADOWOPS-DOM-012, business id
MEADOWOPS-DOMAIN-010, PRD 5.9/S1-FR-14).

Adds `query_log` to the `live` schema (see app/db/query_log.py's module
docstring for why it lives there rather than a new schema, despite the
admin panel eventually reading it too, at Unit 28).

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "query_log",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column(
            "statement_type",
            sa.Enum("read", "write", "unknown", name="query_statement_type", schema="live"),
            nullable=False,
        ),
        sa.Column(
            "result_status",
            sa.Enum(
                "success",
                "error",
                "timed_out",
                "cancelled",
                name="query_result_status",
                schema="live",
            ),
            nullable=False,
        ),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["live.user.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="live",
    )


def downgrade() -> None:
    op.drop_table("query_log", schema="live")
    op.execute("DROP TYPE IF EXISTS live.query_result_status")
    op.execute("DROP TYPE IF EXISTS live.query_statement_type")
