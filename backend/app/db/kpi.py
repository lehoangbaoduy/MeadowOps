import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


class KpiSnapshot(Base):
    """Unit 14 (MEADOWOPS-DOMAIN-006): one row per simulation_date holding
    the four global-scalar starter KPIs (PRD Appendix A). days_of_supply is
    intentionally not here — it's per product/warehouse, see
    DaysOfSupplySnapshot.

    simulation_date is a "recorded-on" stamp, not an "as-of" figure
    (security review): every starter KPI query (sql/kpi/*.sql, Unit 10) is
    an all-time aggregate with no date filter, so this row holds the
    all-time cumulative value as it stood on simulation_date, not a true
    historical snapshot of what the KPI was on that specific day. See
    app.services.kpi_engine's module docstring."""

    __tablename__ = "kpi_snapshot"
    __table_args__ = (UniqueConstraint("simulation_date", name="uq_kpi_snapshot_simulation_date"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    simulation_date: Mapped[date] = mapped_column(Date, nullable=False)
    otif_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    fill_rate_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    order_cycle_time_days: Mapped[Decimal | None] = mapped_column(Numeric(6, 1), nullable=True)
    perfect_order_rate_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class DaysOfSupplySnapshot(Base):
    """Unit 14: one row per (simulation_date, product, warehouse) — the one
    starter KPI that isn't a single global scalar. Same "recorded-on, not
    as-of" caveat as KpiSnapshot: days_of_supply.sql's own latest-snapshot
    lookup is unbounded by simulation_date too."""

    __tablename__ = "days_of_supply_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "simulation_date",
            "product_id",
            "warehouse_id",
            name="uq_days_of_supply_snapshot_grain",
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    simulation_date: Mapped[date] = mapped_column(Date, nullable=False)
    product_id: Mapped[str] = mapped_column(String, ForeignKey("live.product.id"), nullable=False)
    warehouse_id: Mapped[str] = mapped_column(
        String, ForeignKey("live.warehouse.id"), nullable=False
    )
    days_of_supply: Mapped[Decimal | None] = mapped_column(Numeric(8, 1), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
