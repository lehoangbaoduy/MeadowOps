"""KPI engine snapshot tables (MEADOWOPS-DOMAIN-006, PRD Appendix A).

Two tables, not one EAV-style table, matching the actual shape of Unit
10's starter KPI SQL: otif/fill_rate/order_cycle_time/perfect_order_rate
each return a single global scalar per simulation_date (kpi_snapshot, one
row per day); days_of_supply returns one row per product/warehouse
(days_of_supply_snapshot) since it's inherently not a single number.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kpi_snapshot",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("simulation_date", sa.Date(), nullable=False),
        sa.Column("otif_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("fill_rate_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("order_cycle_time_days", sa.Numeric(6, 1), nullable=True),
        sa.Column("perfect_order_rate_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("simulation_date", name="uq_kpi_snapshot_simulation_date"),
        schema="live",
    )
    op.create_table(
        "days_of_supply_snapshot",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("simulation_date", sa.Date(), nullable=False),
        sa.Column("product_id", sa.String(), nullable=False),
        sa.Column("warehouse_id", sa.String(), nullable=False),
        sa.Column("days_of_supply", sa.Numeric(8, 1), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["product_id"], ["live.product.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["live.warehouse.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "simulation_date",
            "product_id",
            "warehouse_id",
            name="uq_days_of_supply_snapshot_grain",
        ),
        schema="live",
    )


def downgrade() -> None:
    op.drop_table("days_of_supply_snapshot", schema="live")
    op.drop_table("kpi_snapshot", schema="live")
