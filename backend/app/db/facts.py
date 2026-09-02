import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, pg_enum
from app.db.enums import (
    InventoryTransactionType,
    PurchaseOrderStatus,
    SalesOrderStatus,
    ShipmentStatus,
    SourceSystem,
    TransferStatus,
)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


class InventorySnapshot(Base):
    __tablename__ = "inventory_snapshot"
    __table_args__ = (
        CheckConstraint("quantity_on_hand >= 0", name="ck_inventory_snapshot_qoh_non_negative"),
        CheckConstraint(
            "quantity_allocated >= 0", name="ck_inventory_snapshot_qalloc_non_negative"
        ),
        UniqueConstraint(
            "snapshot_date", "product_id", "warehouse_id", name="uq_inventory_snapshot_grain"
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    product_id: Mapped[str] = mapped_column(String, ForeignKey("live.product.id"), nullable=False)
    warehouse_id: Mapped[str] = mapped_column(
        String, ForeignKey("live.warehouse.id"), nullable=False
    )
    quantity_on_hand: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_allocated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_system: Mapped[SourceSystem] = mapped_column(
        pg_enum(SourceSystem, "source_system"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class InventoryTransaction(Base):
    __tablename__ = "inventory_transaction"

    id: Mapped[uuid.UUID] = _uuid_pk()
    transaction_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    product_id: Mapped[str] = mapped_column(String, ForeignKey("live.product.id"), nullable=False)
    warehouse_id: Mapped[str] = mapped_column(
        String, ForeignKey("live.warehouse.id"), nullable=False
    )
    transaction_type: Mapped[InventoryTransactionType] = mapped_column(
        pg_enum(InventoryTransactionType, "inventory_transaction_type"), nullable=False
    )
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String, nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_system: Mapped[SourceSystem] = mapped_column(
        pg_enum(SourceSystem, "source_system"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class PurchaseOrder(Base, TimestampMixin):
    __tablename__ = "purchase_order"

    id: Mapped[uuid.UUID] = _uuid_pk()
    po_number: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    supplier_id: Mapped[str] = mapped_column(
        String, ForeignKey("live.supplier.id"), nullable=False
    )
    warehouse_id: Mapped[str] = mapped_column(
        String, ForeignKey("live.warehouse.id"), nullable=False
    )
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_delivery_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[PurchaseOrderStatus] = mapped_column(
        pg_enum(PurchaseOrderStatus, "purchase_order_status"), nullable=False
    )
    source_system: Mapped[SourceSystem] = mapped_column(
        pg_enum(SourceSystem, "source_system"), nullable=False
    )


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_line"
    __table_args__ = (
        CheckConstraint("quantity_ordered >= 0", name="ck_po_line_qordered_non_negative"),
        CheckConstraint("quantity_received >= 0", name="ck_po_line_qreceived_non_negative"),
        CheckConstraint("unit_cost >= 0", name="ck_po_line_unit_cost_non_negative"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live.purchase_order.id"), nullable=False
    )
    product_id: Mapped[str] = mapped_column(String, ForeignKey("live.product.id"), nullable=False)
    quantity_ordered: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_cost: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)


class SalesOrder(Base, TimestampMixin):
    __tablename__ = "sales_order"

    id: Mapped[uuid.UUID] = _uuid_pk()
    so_number: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    customer_id: Mapped[str] = mapped_column(
        String, ForeignKey("live.customer.id"), nullable=False
    )
    warehouse_id: Mapped[str] = mapped_column(
        String, ForeignKey("live.warehouse.id"), nullable=False
    )
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    requested_date: Mapped[date] = mapped_column(Date, nullable=False)
    promised_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[SalesOrderStatus] = mapped_column(
        pg_enum(SalesOrderStatus, "sales_order_status"), nullable=False
    )
    source_system: Mapped[SourceSystem] = mapped_column(
        pg_enum(SourceSystem, "source_system"), nullable=False
    )


class SalesOrderLine(Base):
    __tablename__ = "sales_order_line"
    __table_args__ = (
        CheckConstraint("quantity_ordered >= 0", name="ck_so_line_qordered_non_negative"),
        CheckConstraint("quantity_shipped >= 0", name="ck_so_line_qshipped_non_negative"),
        CheckConstraint("unit_price >= 0", name="ck_so_line_unit_price_non_negative"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    sales_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live.sales_order.id"), nullable=False
    )
    product_id: Mapped[str] = mapped_column(String, ForeignKey("live.product.id"), nullable=False)
    quantity_ordered: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_shipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)


class Shipment(Base, TimestampMixin):
    __tablename__ = "shipment"

    id: Mapped[uuid.UUID] = _uuid_pk()
    sales_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live.sales_order.id"), nullable=False
    )
    carrier_id: Mapped[str] = mapped_column(String, ForeignKey("live.carrier.id"), nullable=False)
    warehouse_id: Mapped[str] = mapped_column(
        String, ForeignKey("live.warehouse.id"), nullable=False
    )
    ship_date: Mapped[date] = mapped_column(Date, nullable=False)
    promised_delivery_date: Mapped[date] = mapped_column(Date, nullable=False)
    actual_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[ShipmentStatus] = mapped_column(
        pg_enum(ShipmentStatus, "shipment_status"), nullable=False
    )
    source_system: Mapped[SourceSystem] = mapped_column(
        pg_enum(SourceSystem, "source_system"), nullable=False
    )


class WarehouseTransfer(Base, TimestampMixin):
    __tablename__ = "warehouse_transfer"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_warehouse_transfer_quantity_positive"),
        CheckConstraint(
            "from_warehouse_id != to_warehouse_id", name="ck_warehouse_transfer_distinct_warehouses"
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    product_id: Mapped[str] = mapped_column(String, ForeignKey("live.product.id"), nullable=False)
    from_warehouse_id: Mapped[str] = mapped_column(
        String, ForeignKey("live.warehouse.id"), nullable=False
    )
    to_warehouse_id: Mapped[str] = mapped_column(
        String, ForeignKey("live.warehouse.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    transfer_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[TransferStatus] = mapped_column(
        pg_enum(TransferStatus, "transfer_status"), nullable=False
    )
    source_system: Mapped[SourceSystem] = mapped_column(
        pg_enum(SourceSystem, "source_system"), nullable=False
    )
