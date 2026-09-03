"""Scheduled procure-to-stock / order-to-ship flow (MEADOWOPS-DOM-006).

Adds three observability/audit tables: scheduled_tick (one row per
scheduled-flow execution), purchase_order_lifecycle_event and
sales_order_lifecycle_event (status-transition audit trails, from_status
null for the creation event).

Note: autogenerate spuriously proposed dropping migration 0009's
ux_world_state_single_clean_baseline_root partial unique index — a known
Alembic limitation correlating a raw op.create_index(..., postgresql_where=)
call back to ORM metadata, not an actual model drift. That drop/recreate
pair is deliberately excluded from this migration; the index is untouched.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scheduled_tick",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("simulation_date", sa.Date(), nullable=False),
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("events_generated", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("success", "failed", name="scheduled_tick_status", schema="live"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="live",
    )
    op.create_table(
        "purchase_order_lifecycle_event",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("purchase_order_id", sa.UUID(), nullable=False),
        sa.Column(
            "from_status",
            postgresql.ENUM(
                "draft",
                "submitted",
                "confirmed",
                "partially_received",
                "received",
                "cancelled",
                name="purchase_order_status",
                schema="live",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "to_status",
            postgresql.ENUM(
                "draft",
                "submitted",
                "confirmed",
                "partially_received",
                "received",
                "cancelled",
                name="purchase_order_status",
                schema="live",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("simulation_date", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["live.purchase_order.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="live",
    )
    op.create_table(
        "sales_order_lifecycle_event",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("sales_order_id", sa.UUID(), nullable=False),
        sa.Column(
            "from_status",
            postgresql.ENUM(
                "draft",
                "submitted",
                "allocated",
                "partially_shipped",
                "shipped",
                "cancelled",
                name="sales_order_status",
                schema="live",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "to_status",
            postgresql.ENUM(
                "draft",
                "submitted",
                "allocated",
                "partially_shipped",
                "shipped",
                "cancelled",
                name="sales_order_status",
                schema="live",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("simulation_date", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["sales_order_id"], ["live.sales_order.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="live",
    )


def downgrade() -> None:
    op.drop_table("sales_order_lifecycle_event", schema="live")
    op.drop_table("purchase_order_lifecycle_event", schema="live")
    op.drop_table("scheduled_tick", schema="live")
    sa.Enum(name="scheduled_tick_status", schema="live").drop(op.get_bind(), checkfirst=True)
