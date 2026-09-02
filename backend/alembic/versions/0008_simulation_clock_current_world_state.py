"""Simulation clock current-world-state pointer (MEADOWOPS-DOM-005).

Unit 4 left world_state's "current head" undiscoverable except by row
ordering, and Postgres's now() is frozen per-transaction-start (not
per-statement) - two world_state rows inserted within the same open
transaction get an identical created_at, so ORDER BY created_at DESC
LIMIT 1 cannot reliably answer "which is current" for composed operations
within one caller transaction (Unit 12a: snapshot/reset need this answer,
and Unit 12a's service functions deliberately don't commit internally so a
future caller can compose them inside one request transaction - see the
service module docstring). simulation_clock is the one true singleton
(PRD 4.2), the natural place to track this explicitly rather than infer it
from timestamp ordering.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "simulation_clock",
        sa.Column("current_world_state_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="live",
    )
    op.create_foreign_key(
        "fk_simulation_clock_current_world_state",
        source_table="simulation_clock",
        referent_table="world_state",
        local_cols=["current_world_state_id"],
        remote_cols=["id"],
        source_schema="live",
        referent_schema="live",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_simulation_clock_current_world_state",
        "simulation_clock",
        schema="live",
        type_="foreignkey",
    )
    op.drop_column("simulation_clock", "current_world_state_id", schema="live")
