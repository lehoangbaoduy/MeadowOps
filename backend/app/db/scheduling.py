import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, pg_enum
from app.db.enums import PurchaseOrderStatus, SalesOrderStatus, ScheduledTickStatus


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


class ScheduledTick(Base):
    """Unit 13 (MEADOWOPS-DOM-006): one execution record per scheduled
    procure-to-stock/order-to-ship pass, for observability and testing —
    not itself part of any KPI/exception calculation."""

    __tablename__ = "scheduled_tick"

    id: Mapped[uuid.UUID] = _uuid_pk()
    simulation_date: Mapped[date] = mapped_column(Date, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    events_generated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[ScheduledTickStatus] = mapped_column(
        pg_enum(ScheduledTickStatus, "scheduled_tick_status"), nullable=False
    )


class PurchaseOrderLifecycleEvent(Base):
    """Audit trail of purchase_order.status transitions driven by the
    scheduled flow — from_status is null for the creation event."""

    __tablename__ = "purchase_order_lifecycle_event"

    id: Mapped[uuid.UUID] = _uuid_pk()
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live.purchase_order.id"), nullable=False
    )
    from_status: Mapped[PurchaseOrderStatus | None] = mapped_column(
        pg_enum(PurchaseOrderStatus, "purchase_order_status"), nullable=True
    )
    to_status: Mapped[PurchaseOrderStatus] = mapped_column(
        pg_enum(PurchaseOrderStatus, "purchase_order_status"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    simulation_date: Mapped[date] = mapped_column(Date, nullable=False)


class SalesOrderLifecycleEvent(Base):
    """Audit trail of sales_order.status transitions driven by the
    scheduled flow — from_status is null for the creation event."""

    __tablename__ = "sales_order_lifecycle_event"

    id: Mapped[uuid.UUID] = _uuid_pk()
    sales_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live.sales_order.id"), nullable=False
    )
    from_status: Mapped[SalesOrderStatus | None] = mapped_column(
        pg_enum(SalesOrderStatus, "sales_order_status"), nullable=True
    )
    to_status: Mapped[SalesOrderStatus] = mapped_column(
        pg_enum(SalesOrderStatus, "sales_order_status"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    simulation_date: Mapped[date] = mapped_column(Date, nullable=False)
