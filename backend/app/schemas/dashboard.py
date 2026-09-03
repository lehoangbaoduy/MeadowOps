"""Unit 16 (MEADOWOPS-API-003): read schemas for the dashboard API's five
S1-FR-5 views (Executive, Inventory, Supplier, Order, Data-Quality) plus
their drill-down endpoints. Every schema here is response-only — this
module has no Create/Update counterparts, since the dashboard never writes
(app.api.dashboard, same as app.schemas.customers)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.db.enums import PurchaseOrderStatus, SalesOrderStatus, ShipmentStatus


class ExecutiveKpiRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    simulation_date: date
    otif_pct: Decimal | None
    fill_rate_pct: Decimal | None
    order_cycle_time_days: Decimal | None
    perfect_order_rate_pct: Decimal | None
    computed_at: datetime


class ExceptionCountByCategory(BaseModel):
    category: str
    open_count: int


class ExecutiveSummaryRead(BaseModel):
    # None only until the scheduler's first tick ever runs — no
    # KpiSnapshot row exists yet (matches KpiSnapshot's own "recorded-on,
    # not point-in-time" semantics: there is no meaningful "current" KPI
    # value before that first tick, so this is None rather than a row of
    # all-null scalars).
    kpis: ExecutiveKpiRead | None
    open_exception_counts: list[ExceptionCountByCategory]


class InventoryPositionRead(BaseModel):
    product_id: str
    warehouse_id: str
    quantity_on_hand: int | None
    quantity_allocated: int | None
    days_of_supply: Decimal | None
    is_low_stock: bool


class InventoryTransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    transaction_at: datetime
    transaction_type: str
    quantity_delta: int
    reference_type: str | None
    reference_id: uuid.UUID | None
    source_system: str


class SupplierPerformanceRead(BaseModel):
    supplier_id: str
    supplier_name: str
    total_purchase_order_count: int
    open_purchase_order_count: int
    at_risk_purchase_order_count: int


class PurchaseOrderSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    po_number: str
    supplier_id: str
    warehouse_id: str
    order_date: date
    expected_delivery_date: date
    status: PurchaseOrderStatus
    # Defaulted, not required: populated via .model_copy(update=...) after
    # model_validate(po, from_attributes=True), since is_at_risk isn't an
    # ORM column — it's derived from ExceptionFlag, computed by the caller.
    is_at_risk: bool = False


class PurchaseOrderLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: str
    quantity_ordered: int
    quantity_received: int
    unit_cost: Decimal


class PurchaseOrderLifecycleEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_status: PurchaseOrderStatus | None
    to_status: PurchaseOrderStatus
    occurred_at: datetime
    simulation_date: date


class PurchaseOrderDetailRead(PurchaseOrderSummaryRead):
    lines: list[PurchaseOrderLineRead]
    lifecycle_events: list[PurchaseOrderLifecycleEventRead]


class SalesOrderSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    so_number: str
    customer_id: str
    warehouse_id: str
    order_date: date
    requested_date: date
    promised_date: date | None
    status: SalesOrderStatus


class SalesOrderLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: str
    quantity_ordered: int
    quantity_shipped: int
    unit_price: Decimal


class SalesOrderLifecycleEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_status: SalesOrderStatus | None
    to_status: SalesOrderStatus
    occurred_at: datetime
    simulation_date: date


class ShipmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sales_order_id: uuid.UUID
    carrier_id: str
    warehouse_id: str
    ship_date: date
    promised_delivery_date: date
    actual_delivery_date: date | None
    status: ShipmentStatus
    # Same derived-field convention as PurchaseOrderSummaryRead.is_at_risk.
    is_late: bool = False


class SalesOrderDetailRead(SalesOrderSummaryRead):
    lines: list[SalesOrderLineRead]
    lifecycle_events: list[SalesOrderLifecycleEventRead]
    shipments: list[ShipmentRead]


class ExceptionFlagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: str
    product_id: str | None
    warehouse_id: str | None
    purchase_order_id: uuid.UUID | None
    shipment_id: uuid.UUID | None
    simulation_date: date
    first_detected_simulation_date: date
    measured_value: Decimal | None
    threshold_value: Decimal
    detected_at: datetime
    resolved_at: datetime | None


class ExceptionDrilldownRead(BaseModel):
    flag: ExceptionFlagRead
    purchase_order: PurchaseOrderSummaryRead | None = None
    shipment: ShipmentRead | None = None
    inventory: InventoryPositionRead | None = None
