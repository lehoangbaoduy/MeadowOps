"""Reporting layer: inventory_snapshot + sync_state (MEADOWOPS-DOM-009,
SR-2/S1-FR-9).

Adds tables to the `reporting` schema — that schema already exists and is
already access-controlled (0001_create_schemas_and_sandbox_role.py: `CREATE
SCHEMA IF NOT EXISTS reporting`, then `REVOKE ALL ... FROM PUBLIC` /
`FROM meadowops_sandbox` on it, same as `live`/`engine`), so this migration
needs no CREATE SCHEMA or REVOKE/GRANT statements of its own.

sync_state is a singleton table (one row, id="default", created lazily by
app.services.reporting_sync on first sync rather than seeded here — no
meaningful "empty" row to insert at migration time, same reasoning
0004/0008 apply to simulation_clock's own singleton row).

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inventory_snapshot",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("product_id", sa.String(), nullable=False),
        sa.Column("warehouse_id", sa.String(), nullable=False),
        sa.Column("quantity_on_hand", sa.Integer(), nullable=False),
        sa.Column("quantity_allocated", sa.Integer(), nullable=False),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["product_id"], ["live.product.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["live.warehouse.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_date",
            "product_id",
            "warehouse_id",
            name="uq_reporting_inventory_snapshot_grain",
        ),
        schema="reporting",
    )
    op.create_table(
        "sync_state",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("last_synced_simulation_date", sa.Date(), nullable=True),
        sa.Column("frozen_conflict_product_id", sa.String(), nullable=True),
        sa.Column("frozen_conflict_warehouse_id", sa.String(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["frozen_conflict_product_id"], ["live.product.id"]),
        sa.ForeignKeyConstraint(["frozen_conflict_warehouse_id"], ["live.warehouse.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="reporting",
    )


def downgrade() -> None:
    op.drop_table("sync_state", schema="reporting")
    op.drop_table("inventory_snapshot", schema="reporting")
