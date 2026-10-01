"""Unit 41 (MEADOWOPS-DOM-029): the aggregates behind the Overview page.

Read-only and honest by construction: every figure is a COUNT/SUM/AVG over
rows that already exist (sales orders, shipments, purchase orders, stock
snapshots, KPI snapshots, exception flags). Nothing is estimated, smoothed or
back-filled; days with no activity are simply zero so charts keep a
continuous axis. The window is the trailing `days` days ending on the current
simulation date, since that is "now" inside the simulated company.

One deliberate limit, inherited from app.services.kpi_engine: a KPI snapshot
is the cumulative figure as it stood on its date, not that single day's
value, so the KPI trend is a running figure, not a daily one.
"""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.dimensions import Product, Supplier, Warehouse
from app.db.enums import PurchaseOrderStatus, ShipmentStatus
from app.db.exception_flags import ExceptionFlag
from app.db.facts import (
    InventorySnapshot,
    PurchaseOrder,
    SalesOrder,
    SalesOrderLine,
    Shipment,
)
from app.db.kpi import DaysOfSupplySnapshot, KpiSnapshot
from app.db.scheduling import PurchaseOrderLifecycleEvent, ScheduledTick
from app.db.world_state import SimulationClock
from app.schemas.dashboard import (
    ExceptionCountByCategory,
    OverviewCount,
    OverviewDailyActivity,
    OverviewExceptionDay,
    OverviewKpiPoint,
    OverviewProductDemand,
    OverviewRead,
    OverviewShipmentBreakdown,
    OverviewSupplier,
    OverviewWarehouse,
)
from app.services.exception_engine import AT_RISK_PO_CATEGORY, LOW_STOCK_CATEGORY

TOP_PRODUCT_COUNT = 8
_OPEN_PO_STATUSES = (
    PurchaseOrderStatus.SUBMITTED,
    PurchaseOrderStatus.CONFIRMED,
    PurchaseOrderStatus.PARTIALLY_RECEIVED,
)
_ONE_DECIMAL = Decimal("0.1")


def _by_date(rows) -> dict[date, tuple]:
    return {row[0]: row[1:] for row in rows}


def _daily_activity(
    session: Session, start: date, end: date
) -> list[OverviewDailyActivity]:
    in_window = lambda column: column.between(start, end)  # noqa: E731

    orders = _by_date(
        session.execute(
            select(SalesOrder.order_date, func.count(func.distinct(SalesOrder.id)))
            .where(in_window(SalesOrder.order_date))
            .group_by(SalesOrder.order_date)
        )
    )
    values = _by_date(
        session.execute(
            select(
                SalesOrder.order_date,
                func.coalesce(
                    func.sum(SalesOrderLine.quantity_ordered * SalesOrderLine.unit_price), 0
                ),
            )
            .join(SalesOrderLine, SalesOrderLine.sales_order_id == SalesOrder.id)
            .where(in_window(SalesOrder.order_date))
            .group_by(SalesOrder.order_date)
        )
    )
    shipped = _by_date(
        session.execute(
            select(Shipment.ship_date, func.count())
            .where(in_window(Shipment.ship_date))
            .group_by(Shipment.ship_date)
        )
    )
    on_time = Shipment.actual_delivery_date <= Shipment.promised_delivery_date
    delivered = _by_date(
        session.execute(
            select(
                Shipment.actual_delivery_date,
                func.count().filter(on_time),
                func.count().filter(~on_time),
            )
            .where(
                Shipment.status == ShipmentStatus.DELIVERED,
                in_window(Shipment.actual_delivery_date),
            )
            .group_by(Shipment.actual_delivery_date)
        )
    )
    purchase_orders = _by_date(
        session.execute(
            select(PurchaseOrder.order_date, func.count())
            .where(in_window(PurchaseOrder.order_date))
            .group_by(PurchaseOrder.order_date)
        )
    )

    days = [start + timedelta(days=n) for n in range((end - start).days + 1)]
    return [
        OverviewDailyActivity(
            simulation_date=day,
            orders_placed=orders.get(day, (0,))[0],
            order_value=Decimal(values.get(day, (0,))[0]),
            shipments_shipped=shipped.get(day, (0,))[0],
            delivered_on_time=delivered.get(day, (0, 0))[0],
            delivered_late=delivered.get(day, (0, 0))[1],
            purchase_orders_placed=purchase_orders.get(day, (0,))[0],
        )
        for day in days
    ]


def _shipment_breakdown(session: Session, start: date, end: date) -> OverviewShipmentBreakdown:
    on_time = Shipment.actual_delivery_date <= Shipment.promised_delivery_date
    delivered = Shipment.status == ShipmentStatus.DELIVERED
    row = session.execute(
        select(
            func.count().filter(delivered & on_time),
            func.count().filter(delivered & ~on_time),
            func.count().filter(
                Shipment.status.in_((ShipmentStatus.PENDING, ShipmentStatus.IN_TRANSIT))
            ),
            func.count().filter(Shipment.status == ShipmentStatus.EXCEPTION),
        ).where(Shipment.ship_date.between(start, end))
    ).one()
    return OverviewShipmentBreakdown(
        delivered_on_time=row[0], delivered_late=row[1], in_progress=row[2], exception=row[3]
    )


def _inventory_by_warehouse(session: Session) -> list[OverviewWarehouse]:
    latest_snapshot = session.scalar(select(func.max(InventorySnapshot.snapshot_date)))
    stock = {}
    if latest_snapshot is not None:
        stock = {
            warehouse_id: (on_hand, allocated)
            for warehouse_id, on_hand, allocated in session.execute(
                select(
                    InventorySnapshot.warehouse_id,
                    func.sum(InventorySnapshot.quantity_on_hand),
                    func.sum(InventorySnapshot.quantity_allocated),
                )
                .where(InventorySnapshot.snapshot_date == latest_snapshot)
                .group_by(InventorySnapshot.warehouse_id)
            )
        }
    latest_supply = session.scalar(select(func.max(DaysOfSupplySnapshot.simulation_date)))
    supply = {}
    if latest_supply is not None:
        supply = dict(
            session.execute(
                select(
                    DaysOfSupplySnapshot.warehouse_id, func.avg(DaysOfSupplySnapshot.days_of_supply)
                )
                .where(DaysOfSupplySnapshot.simulation_date == latest_supply)
                .group_by(DaysOfSupplySnapshot.warehouse_id)
            ).all()
        )
    low_stock = dict(
        session.execute(
            select(ExceptionFlag.warehouse_id, func.count())
            .where(
                ExceptionFlag.category == LOW_STOCK_CATEGORY,
                ExceptionFlag.resolved_at.is_(None),
            )
            .group_by(ExceptionFlag.warehouse_id)
        ).all()
    )
    warehouses = session.execute(
        select(Warehouse.id, Warehouse.name)
        .where(Warehouse.is_active.is_(True))
        .order_by(Warehouse.id)
    ).all()
    return [
        OverviewWarehouse(
            warehouse_id=warehouse_id,
            warehouse_name=name,
            units_on_hand=int(stock.get(warehouse_id, (0, 0))[0] or 0),
            units_allocated=int(stock.get(warehouse_id, (0, 0))[1] or 0),
            avg_days_of_supply=(
                Decimal(supply[warehouse_id]).quantize(_ONE_DECIMAL, ROUND_HALF_UP)
                if supply.get(warehouse_id) is not None
                else None
            ),
            low_stock_positions=low_stock.get(warehouse_id, 0),
        )
        for warehouse_id, name in warehouses
    ]


def _suppliers(session: Session, start: date, end: date) -> list[OverviewSupplier]:
    placed = dict(
        session.execute(
            select(PurchaseOrder.supplier_id, func.count())
            .where(PurchaseOrder.order_date.between(start, end))
            .group_by(PurchaseOrder.supplier_id)
        ).all()
    )
    received_at = (
        select(
            PurchaseOrderLifecycleEvent.purchase_order_id.label("po_id"),
            func.min(PurchaseOrderLifecycleEvent.simulation_date).label("received_on"),
        )
        .where(PurchaseOrderLifecycleEvent.to_status == PurchaseOrderStatus.RECEIVED)
        .group_by(PurchaseOrderLifecycleEvent.purchase_order_id)
        .subquery()
    )
    received = {
        supplier_id: (total, on_time)
        for supplier_id, total, on_time in session.execute(
            select(
                PurchaseOrder.supplier_id,
                func.count(),
                func.count().filter(received_at.c.received_on <= PurchaseOrder.expected_delivery_date),
            )
            .join(received_at, received_at.c.po_id == PurchaseOrder.id)
            .where(received_at.c.received_on.between(start, end))
            .group_by(PurchaseOrder.supplier_id)
        )
    }
    open_counts = dict(
        session.execute(
            select(PurchaseOrder.supplier_id, func.count())
            .where(PurchaseOrder.status.in_(_OPEN_PO_STATUSES))
            .group_by(PurchaseOrder.supplier_id)
        ).all()
    )
    at_risk = dict(
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
    suppliers = session.execute(
        select(Supplier.id, Supplier.name).where(Supplier.is_active.is_(True)).order_by(Supplier.id)
    ).all()
    result = []
    for supplier_id, name in suppliers:
        total, on_time = received.get(supplier_id, (0, 0))
        result.append(
            OverviewSupplier(
                supplier_id=supplier_id,
                supplier_name=name,
                purchase_orders_placed=placed.get(supplier_id, 0),
                purchase_orders_received=total,
                received_on_time=on_time,
                on_time_receipt_pct=(
                    (Decimal(on_time) * 100 / Decimal(total)).quantize(_ONE_DECIMAL, ROUND_HALF_UP)
                    if total
                    else None
                ),
                open_purchase_orders=open_counts.get(supplier_id, 0),
                at_risk_purchase_orders=at_risk.get(supplier_id, 0),
            )
        )
    return result


def _top_products(session: Session, start: date, end: date) -> list[OverviewProductDemand]:
    ordered = func.sum(SalesOrderLine.quantity_ordered)
    rows = session.execute(
        select(Product.id, Product.name, ordered, func.sum(SalesOrderLine.quantity_shipped))
        .join(SalesOrderLine, SalesOrderLine.product_id == Product.id)
        .join(SalesOrder, SalesOrder.id == SalesOrderLine.sales_order_id)
        .where(SalesOrder.order_date.between(start, end))
        .group_by(Product.id, Product.name)
        .order_by(ordered.desc(), Product.id)
        .limit(TOP_PRODUCT_COUNT)
    ).all()
    return [
        OverviewProductDemand(
            product_id=pid, product_name=name, units_ordered=int(qty), units_shipped=int(shipped)
        )
        for pid, name, qty, shipped in rows
    ]


def build_overview(session: Session, *, days: int) -> OverviewRead:
    if days < 1:
        raise ValueError("days must be at least 1")
    as_of = session.scalar(select(SimulationClock.simulation_date).where(SimulationClock.id == 1))
    if as_of is None:
        as_of = date.today()
    start = as_of - timedelta(days=days - 1)
    # Days before the simulation recorded anything are "no data", not "zero
    # activity" - never draw them. With no tick history at all the requested
    # window stands, and the page shows its empty states.
    first_recorded = session.scalar(select(func.min(ScheduledTick.simulation_date)))
    if first_recorded is not None and first_recorded > start:
        start = min(first_recorded, as_of)
        days = (as_of - start).days + 1

    kpi_rows = session.scalars(
        select(KpiSnapshot)
        .where(KpiSnapshot.simulation_date.between(start, as_of))
        .order_by(KpiSnapshot.simulation_date)
    ).all()
    order_status = session.execute(
        select(SalesOrder.status, func.count())
        .where(SalesOrder.order_date.between(start, as_of))
        .group_by(SalesOrder.status)
        .order_by(func.count().desc())
    ).all()
    open_exceptions = session.execute(
        select(ExceptionFlag.category, func.count())
        .where(ExceptionFlag.resolved_at.is_(None))
        .group_by(ExceptionFlag.category)
        .order_by(ExceptionFlag.category)
    ).all()
    detected = dict(
        session.execute(
            select(ExceptionFlag.first_detected_simulation_date, func.count())
            .where(ExceptionFlag.first_detected_simulation_date.between(start, as_of))
            .group_by(ExceptionFlag.first_detected_simulation_date)
        ).all()
    )

    return OverviewRead(
        as_of=as_of,
        window_start=start,
        window_days=days,
        kpi_trend=[OverviewKpiPoint.model_validate(row) for row in kpi_rows],
        daily_activity=_daily_activity(session, start, as_of),
        sales_order_status=[
            OverviewCount(label=status.value, count=count) for status, count in order_status
        ],
        shipment_delivery=_shipment_breakdown(session, start, as_of),
        inventory_by_warehouse=_inventory_by_warehouse(session),
        suppliers=_suppliers(session, start, as_of),
        top_products=_top_products(session, start, as_of),
        open_exceptions_by_category=[
            ExceptionCountByCategory(category=category, open_count=count)
            for category, count in open_exceptions
        ],
        new_exceptions_per_day=[
            OverviewExceptionDay(
                simulation_date=start + timedelta(days=n),
                count=detected.get(start + timedelta(days=n), 0),
            )
            for n in range(days)
        ],
    )
