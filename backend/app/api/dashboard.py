"""Unit 16 (MEADOWOPS-API-003): dashboard API + drill-down endpoints for the
five S1-FR-5 views (Executive, Inventory, Supplier, Order, Data-Quality).
`require_authenticated` (Unit 17a, MEADOWOPS-DOM-010, DD-22) — read-only
for both Admin and Analyst, GET-only — same conventions as
app/api/customers.py — `def`, not `async def` (sync SQLAlchemy under the
event loop, same rationale as every other route module in this project).

Reads real history from KpiSnapshot/DaysOfSupplySnapshot/ExceptionFlag —
this unit closes B9 (app.domain.scheduler now calls
evaluate_exceptions/compute_and_snapshot_kpis every tick) specifically so
these tables have real rows for the views below to read and drill into,
rather than recomputing every KPI from scratch on every request. Every
summary/count exposed here is a real aggregate over these tables, not a
placeholder — reconciled against its own drill-down rows in
tests/api/test_dashboard.py.

The Supplier view has no PRD Appendix D page mapping (only Unit 8's
master-data CRUD, a different concern) — built net-new from S1-FR-5 itself,
which names Supplier as one of the five required views. See spec id 207
(MEADOWOPS-API-003) for the full endpoint rationale.
"""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import require_authenticated
from app.db.dimensions import Product, Supplier, Warehouse
from app.db.enums import PurchaseOrderStatus, ShipmentStatus
from app.db.exception_flags import ExceptionFlag
from app.db.facts import (
    InventorySnapshot,
    InventoryTransaction,
    PurchaseOrder,
    PurchaseOrderLine,
    SalesOrder,
    SalesOrderLine,
    Shipment,
)
from app.db.kpi import DaysOfSupplySnapshot, KpiSnapshot
from app.db.scheduling import PurchaseOrderLifecycleEvent, SalesOrderLifecycleEvent
from app.db.session import get_session
from app.services.exception_engine import (
    AT_RISK_PO_CATEGORY,
    LATE_SHIPMENT_CATEGORY,
    LOW_STOCK_CATEGORY,
)
from app.schemas.dashboard import (
    ExceptionCountByCategory,
    ExceptionDrilldownRead,
    ExceptionFlagRead,
    ExecutiveKpiRead,
    ExecutiveSummaryRead,
    InventoryPositionRead,
    InventoryTransactionRead,
    PurchaseOrderDetailRead,
    PurchaseOrderLifecycleEventRead,
    PurchaseOrderLineRead,
    PurchaseOrderSummaryRead,
    SalesOrderDetailRead,
    SalesOrderLifecycleEventRead,
    SalesOrderLineRead,
    SalesOrderSummaryRead,
    ShipmentRead,
    SupplierPerformanceRead,
)

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])

# Same open-status sets scheduled_flow.py itself progresses through — a PO
# or shipment outside these is already at rest (received/delivered/
# cancelled) and can't newly become at-risk/late.
_OPEN_PO_STATUSES = (
    PurchaseOrderStatus.SUBMITTED,
    PurchaseOrderStatus.CONFIRMED,
    PurchaseOrderStatus.PARTIALLY_RECEIVED,
)
_IN_FLIGHT_SHIPMENT_STATUSES = (ShipmentStatus.PENDING, ShipmentStatus.IN_TRANSIT)


def _open_flag_ids(session: Session, category: str, id_column) -> set:
    return set(
        session.execute(
            select(id_column).where(
                ExceptionFlag.category == category, ExceptionFlag.resolved_at.is_(None)
            )
        ).scalars()
    )


def _open_low_stock_keys(session: Session) -> set[tuple[str, str]]:
    rows = session.execute(
        select(ExceptionFlag.product_id, ExceptionFlag.warehouse_id).where(
            ExceptionFlag.category == LOW_STOCK_CATEGORY, ExceptionFlag.resolved_at.is_(None)
        )
    ).all()
    return {(r.product_id, r.warehouse_id) for r in rows}


def _latest_days_of_supply(
    session: Session, *, warehouse_id: str | None = None, product_id: str | None = None
) -> dict[tuple[str, str], object]:
    query = select(DaysOfSupplySnapshot)
    if warehouse_id is not None:
        query = query.where(DaysOfSupplySnapshot.warehouse_id == warehouse_id)
    if product_id is not None:
        query = query.where(DaysOfSupplySnapshot.product_id == product_id)
    rows = session.execute(
        query.distinct(DaysOfSupplySnapshot.product_id, DaysOfSupplySnapshot.warehouse_id).order_by(
            DaysOfSupplySnapshot.product_id,
            DaysOfSupplySnapshot.warehouse_id,
            DaysOfSupplySnapshot.simulation_date.desc(),
        )
    ).scalars()
    return {(r.product_id, r.warehouse_id): r.days_of_supply for r in rows}


def _latest_inventory_positions(
    session: Session, *, warehouse_id: str | None = None, product_id: str | None = None
) -> dict[tuple[str, str], InventorySnapshot]:
    query = select(InventorySnapshot)
    if warehouse_id is not None:
        query = query.where(InventorySnapshot.warehouse_id == warehouse_id)
    if product_id is not None:
        query = query.where(InventorySnapshot.product_id == product_id)
    rows = session.execute(
        query.distinct(InventorySnapshot.product_id, InventorySnapshot.warehouse_id).order_by(
            InventorySnapshot.product_id,
            InventorySnapshot.warehouse_id,
            InventorySnapshot.snapshot_date.desc(),
        )
    ).scalars()
    return {(r.product_id, r.warehouse_id): r for r in rows}


def _inventory_position_read(
    product_id: str,
    warehouse_id: str,
    days_of_supply_by_key: dict[tuple[str, str], object],
    snapshot_by_key: dict[tuple[str, str], InventorySnapshot],
    low_stock_keys: set[tuple[str, str]],
) -> InventoryPositionRead:
    key = (product_id, warehouse_id)
    snapshot = snapshot_by_key.get(key)
    return InventoryPositionRead(
        product_id=product_id,
        warehouse_id=warehouse_id,
        quantity_on_hand=snapshot.quantity_on_hand if snapshot else None,
        quantity_allocated=snapshot.quantity_allocated if snapshot else None,
        days_of_supply=days_of_supply_by_key.get(key),
        is_low_stock=key in low_stock_keys,
    )


@router.get("/executive", response_model=ExecutiveSummaryRead)
def get_executive_summary(
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_authenticated),
) -> ExecutiveSummaryRead:
    latest = session.execute(
        select(KpiSnapshot).order_by(KpiSnapshot.simulation_date.desc()).limit(1)
    ).scalar_one_or_none()
    counts = session.execute(
        select(ExceptionFlag.category, func.count())
        .where(ExceptionFlag.resolved_at.is_(None))
        .group_by(ExceptionFlag.category)
    ).all()
    return ExecutiveSummaryRead(
        kpis=ExecutiveKpiRead.model_validate(latest) if latest is not None else None,
        open_exception_counts=[
            ExceptionCountByCategory(category=category, open_count=count)
            for category, count in counts
        ],
    )


@router.get("/executive/trend", response_model=list[ExecutiveKpiRead])
def get_executive_trend(
    limit: int = Query(default=90, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_authenticated),
) -> list[KpiSnapshot]:
    rows = list(
        session.scalars(
            select(KpiSnapshot)
            .order_by(KpiSnapshot.simulation_date.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    rows.reverse()
    return rows


@router.get("/inventory", response_model=list[InventoryPositionRead])
def list_inventory_positions(
    warehouse_id: str | None = Query(default=None),
    product_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_authenticated),
) -> list[InventoryPositionRead]:
    days_of_supply_by_key = _latest_days_of_supply(
        session, warehouse_id=warehouse_id, product_id=product_id
    )
    snapshot_by_key = _latest_inventory_positions(
        session, warehouse_id=warehouse_id, product_id=product_id
    )
    low_stock_keys = _open_low_stock_keys(session)
    keys = set(days_of_supply_by_key) | set(snapshot_by_key)
    return [
        _inventory_position_read(pid, wid, days_of_supply_by_key, snapshot_by_key, low_stock_keys)
        for pid, wid in sorted(keys)
    ]


@router.get(
    "/inventory/{product_id}/{warehouse_id}/transactions",
    response_model=list[InventoryTransactionRead],
)
def list_inventory_transactions(
    product_id: str,
    warehouse_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_authenticated),
) -> list[InventoryTransaction]:
    if session.get(Product, product_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Product not found")
    if session.get(Warehouse, warehouse_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Warehouse not found")
    return list(
        session.scalars(
            select(InventoryTransaction)
            .where(
                InventoryTransaction.product_id == product_id,
                InventoryTransaction.warehouse_id == warehouse_id,
            )
            .order_by(InventoryTransaction.transaction_at.desc())
            .limit(limit)
        )
    )


@router.get("/suppliers", response_model=list[SupplierPerformanceRead])
def list_supplier_performance(
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_authenticated),
) -> list[SupplierPerformanceRead]:
    suppliers = session.execute(
        select(Supplier).where(Supplier.is_active.is_(True)).order_by(Supplier.id)
    ).scalars()
    total_by_supplier = dict(
        session.execute(
            select(PurchaseOrder.supplier_id, func.count()).group_by(PurchaseOrder.supplier_id)
        ).all()
    )
    open_by_supplier = dict(
        session.execute(
            select(PurchaseOrder.supplier_id, func.count())
            .where(PurchaseOrder.status.in_(_OPEN_PO_STATUSES))
            .group_by(PurchaseOrder.supplier_id)
        ).all()
    )
    at_risk_by_supplier = dict(
        session.execute(
            select(PurchaseOrder.supplier_id, func.count())
            .select_from(ExceptionFlag)
            .join(PurchaseOrder, PurchaseOrder.id == ExceptionFlag.purchase_order_id)
            .where(
                ExceptionFlag.category == AT_RISK_PO_CATEGORY,
                ExceptionFlag.resolved_at.is_(None),
            )
            .group_by(PurchaseOrder.supplier_id)
        ).all()
    )
    return [
        SupplierPerformanceRead(
            supplier_id=s.id,
            supplier_name=s.name,
            total_purchase_order_count=total_by_supplier.get(s.id, 0),
            open_purchase_order_count=open_by_supplier.get(s.id, 0),
            at_risk_purchase_order_count=at_risk_by_supplier.get(s.id, 0),
        )
        for s in suppliers
    ]


@router.get(
    "/suppliers/{supplier_id}/purchase-orders", response_model=list[PurchaseOrderSummaryRead]
)
def list_supplier_purchase_orders(
    supplier_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_authenticated),
) -> list[PurchaseOrderSummaryRead]:
    if session.get(Supplier, supplier_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    at_risk_ids = _open_flag_ids(session, AT_RISK_PO_CATEGORY, ExceptionFlag.purchase_order_id)
    rows = session.execute(
        select(PurchaseOrder)
        .where(PurchaseOrder.supplier_id == supplier_id)
        .order_by(PurchaseOrder.order_date.desc())
        .limit(limit)
        .offset(offset)
    ).scalars()
    return [
        PurchaseOrderSummaryRead.model_validate(po).model_copy(
            update={"is_at_risk": po.id in at_risk_ids}
        )
        for po in rows
    ]


@router.get("/orders/purchase", response_model=list[PurchaseOrderSummaryRead])
def list_purchase_orders(
    warehouse_id: str | None = Query(default=None),
    supplier_id: str | None = Query(default=None),
    status_: PurchaseOrderStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_authenticated),
) -> list[PurchaseOrderSummaryRead]:
    at_risk_ids = _open_flag_ids(session, AT_RISK_PO_CATEGORY, ExceptionFlag.purchase_order_id)
    query = select(PurchaseOrder)
    if warehouse_id is not None:
        query = query.where(PurchaseOrder.warehouse_id == warehouse_id)
    if supplier_id is not None:
        query = query.where(PurchaseOrder.supplier_id == supplier_id)
    if status_ is not None:
        query = query.where(PurchaseOrder.status == status_)
    rows = session.execute(
        query.order_by(PurchaseOrder.order_date.desc()).limit(limit).offset(offset)
    ).scalars()
    return [
        PurchaseOrderSummaryRead.model_validate(po).model_copy(
            update={"is_at_risk": po.id in at_risk_ids}
        )
        for po in rows
    ]


@router.get("/orders/purchase/{purchase_order_id}", response_model=PurchaseOrderDetailRead)
def get_purchase_order_detail(
    purchase_order_id: uuid.UUID,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_authenticated),
) -> PurchaseOrderDetailRead:
    po = session.get(PurchaseOrder, purchase_order_id)
    if po is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Purchase order not found")
    is_at_risk = (
        session.execute(
            select(ExceptionFlag.id).where(
                ExceptionFlag.category == AT_RISK_PO_CATEGORY,
                ExceptionFlag.purchase_order_id == purchase_order_id,
                ExceptionFlag.resolved_at.is_(None),
            )
        ).first()
        is not None
    )
    lines = session.execute(
        select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == purchase_order_id)
    ).scalars()
    events = session.execute(
        select(PurchaseOrderLifecycleEvent)
        .where(PurchaseOrderLifecycleEvent.purchase_order_id == purchase_order_id)
        .order_by(PurchaseOrderLifecycleEvent.occurred_at)
    ).scalars()
    summary = PurchaseOrderSummaryRead.model_validate(po).model_copy(
        update={"is_at_risk": is_at_risk}
    )
    return PurchaseOrderDetailRead(
        **summary.model_dump(),
        lines=[PurchaseOrderLineRead.model_validate(line) for line in lines],
        lifecycle_events=[PurchaseOrderLifecycleEventRead.model_validate(e) for e in events],
    )


@router.get("/orders/sales", response_model=list[SalesOrderSummaryRead])
def list_sales_orders(
    warehouse_id: str | None = Query(default=None),
    customer_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_authenticated),
) -> list[SalesOrder]:
    query = select(SalesOrder)
    if warehouse_id is not None:
        query = query.where(SalesOrder.warehouse_id == warehouse_id)
    if customer_id is not None:
        query = query.where(SalesOrder.customer_id == customer_id)
    return list(
        session.scalars(
            query.order_by(SalesOrder.order_date.desc()).limit(limit).offset(offset)
        )
    )


def _shipment_read(shipment: Shipment) -> ShipmentRead:
    is_late = (
        shipment.actual_delivery_date is not None
        and shipment.actual_delivery_date > shipment.promised_delivery_date
    )
    return ShipmentRead.model_validate(shipment).model_copy(update={"is_late": is_late})


@router.get("/orders/sales/{sales_order_id}", response_model=SalesOrderDetailRead)
def get_sales_order_detail(
    sales_order_id: uuid.UUID,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_authenticated),
) -> SalesOrderDetailRead:
    so = session.get(SalesOrder, sales_order_id)
    if so is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Sales order not found")
    lines = session.execute(
        select(SalesOrderLine).where(SalesOrderLine.sales_order_id == sales_order_id)
    ).scalars()
    events = session.execute(
        select(SalesOrderLifecycleEvent)
        .where(SalesOrderLifecycleEvent.sales_order_id == sales_order_id)
        .order_by(SalesOrderLifecycleEvent.occurred_at)
    ).scalars()
    shipments = session.execute(
        select(Shipment).where(Shipment.sales_order_id == sales_order_id)
    ).scalars()
    return SalesOrderDetailRead(
        **SalesOrderSummaryRead.model_validate(so).model_dump(),
        lines=[SalesOrderLineRead.model_validate(line) for line in lines],
        lifecycle_events=[SalesOrderLifecycleEventRead.model_validate(e) for e in events],
        shipments=[_shipment_read(s) for s in shipments],
    )


@router.get("/shipments", response_model=list[ShipmentRead])
def list_shipments(
    warehouse_id: str | None = Query(default=None),
    status_: ShipmentStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_authenticated),
) -> list[ShipmentRead]:
    """Appendix D's Shipping page ("Shipment tracking / OTIF drill-down") —
    the one Order-view drill-down flat enough to be its own list rather
    than only reachable by first opening a sales order."""
    query = select(Shipment)
    if warehouse_id is not None:
        query = query.where(Shipment.warehouse_id == warehouse_id)
    if status_ is not None:
        query = query.where(Shipment.status == status_)
    rows = session.execute(
        query.order_by(Shipment.ship_date.desc()).limit(limit).offset(offset)
    ).scalars()
    return [_shipment_read(s) for s in rows]


@router.get("/exceptions", response_model=list[ExceptionFlagRead])
def list_exceptions(
    category: str | None = Query(default=None),
    include_resolved: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_authenticated),
) -> list[ExceptionFlag]:
    query = select(ExceptionFlag)
    if category is not None:
        query = query.where(ExceptionFlag.category == category)
    if not include_resolved:
        query = query.where(ExceptionFlag.resolved_at.is_(None))
    return list(
        session.scalars(
            query.order_by(ExceptionFlag.detected_at.desc()).limit(limit).offset(offset)
        )
    )


@router.get("/exceptions/{exception_flag_id}", response_model=ExceptionDrilldownRead)
def get_exception_drilldown(
    exception_flag_id: uuid.UUID,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_authenticated),
) -> ExceptionDrilldownRead:
    flag = session.get(ExceptionFlag, exception_flag_id)
    if flag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Exception flag not found")

    purchase_order = None
    if flag.category == AT_RISK_PO_CATEGORY and flag.purchase_order_id is not None:
        po = session.get(PurchaseOrder, flag.purchase_order_id)
        if po is not None:
            is_at_risk = flag.resolved_at is None
            purchase_order = PurchaseOrderSummaryRead.model_validate(po).model_copy(
                update={"is_at_risk": is_at_risk}
            )

    shipment = None
    if flag.category == LATE_SHIPMENT_CATEGORY and flag.shipment_id is not None:
        s = session.get(Shipment, flag.shipment_id)
        if s is not None:
            shipment = _shipment_read(s)

    inventory = None
    if flag.category == LOW_STOCK_CATEGORY and flag.product_id and flag.warehouse_id:
        days_of_supply_by_key = _latest_days_of_supply(
            session, warehouse_id=flag.warehouse_id, product_id=flag.product_id
        )
        snapshot_by_key = _latest_inventory_positions(
            session, warehouse_id=flag.warehouse_id, product_id=flag.product_id
        )
        low_stock_keys = _open_low_stock_keys(session)
        inventory = _inventory_position_read(
            flag.product_id,
            flag.warehouse_id,
            days_of_supply_by_key,
            snapshot_by_key,
            low_stock_keys,
        )

    return ExceptionDrilldownRead(
        flag=ExceptionFlagRead.model_validate(flag),
        purchase_order=purchase_order,
        shipment=shipment,
        inventory=inventory,
    )
