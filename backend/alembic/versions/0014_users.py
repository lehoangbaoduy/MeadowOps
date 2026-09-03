"""Role-based login: live.user (MEADOWOPS-DOM-010, PRD 5.1/8.4 amendment,
S1-FR-16, DD-22).

Replaces the single shared Builder bearer token with two real accounts
(Admin/Analyst) — still just two known users, no self-registration
endpoint anywhere in this codebase. Rows are inserted by
app.services.auth_seed.seed_initial_users, not by this migration (same
"no meaningful seed data at migration time" reasoning 0013's own docstring
gives for sync_state's singleton row).

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("role", sa.Enum("admin", "analyst", name="user_role", schema="live"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_user_email"),
        schema="live",
    )


def downgrade() -> None:
    op.drop_table("user", schema="live")
    op.execute("DROP TYPE IF EXISTS live.user_role")
