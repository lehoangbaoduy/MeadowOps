"""Unit 13 (MEADOWOPS-DOM-006): scheduled procure-to-stock / order-to-ship
flow — the transactional layer. Pure decision logic lives in
app.domain.scheduled_flow, same split as
app.domain.simulation_clock / app.services.simulation_clock_ops.

Each call to run_scheduled_tick(session, simulation_date) is meant to run
once per simulation day, after the clock has already been advanced to that
date (app.services.simulation_clock_ops.advance_simulation) — this module
does not itself touch the clock. Transaction boundaries belong to the
caller (matching simulation_clock_ops's own convention): nothing here
commits except via the caller's own session.commit().

Scope, as amended by Unit 30 (MEADOWOPS-DOM-030, PRD 9.2 catalog row 4):
this unit's original scope note said PurchaseOrderStatus.PARTIALLY_RECEIVED
existed in the schema but nothing produced it — Unit 30 closes that gap.
_progress_purchase_orders now rolls a seeded, real chance
(roll_partial_receipt_fraction) that a receipt tick only partially
fulfills a PO's lines, leaving it PARTIALLY_RECEIVED until a later tick
(re-rolled independently each day) completes it. SO shipments still don't
model partial-quantity fulfillment beyond what "not enough inventory yet"
naturally produces — that remains out of this unit's scope, PRD 9.2's
catalog has no row asking for it.

Unit 27 (MEADOWOPS-DOM-021, business id MEADOWOPS-DOMAIN-016, PRD 3.4/5.2)
activates two more pieces of Phase 1 schema that had sat unused until now:

- WarehouseTransfer / TransferStatus: a low warehouse pulls unallocated
  surplus of the same product from whichever other warehouse has the most
  to spare (never below that donor's own reorder threshold), progressing
  PENDING -> IN_TRANSIT -> COMPLETED over WAREHOUSE_TRANSFER_TRANSIT_DAYS,
  same shape as the PO/shipment progression above. Transfers are created
  before POs each tick, and each guards against the other's open request
  for the same (product, warehouse) so the two mechanisms never double-
  replenish the same shortfall; when no warehouse has any surplus,
  transfers simply create nothing and POs still fire as before.
- Carrier.variability / reliability_pct: a shipment's promised_delivery_date
  is unchanged (still the carrier's average transit time), but its actual
  arrival can now diverge from that promise — carrier_actual_transit_days
  is recomputed from the stable (ship_date, shipment.id) pair every tick,
  so the result doesn't need its own persisted column. This is what makes
  Unit 15's evaluate_late_shipment check reachable for the first time.
  ShipmentStatus.EXCEPTION is deliberately left unused — the PRD's carrier
  table frames reliability_pct as an on-time rate, not a distinct failure
  mode, and evaluate_late_shipment already treats "late" as its own thing.
"""

import logging
import random
import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.dimensions import Carrier, Customer, Product, Supplier, Warehouse
from app.db.enums import (
    InventoryTransactionType,
    PurchaseOrderStatus,
    SalesOrderStatus,
    ScheduledTickStatus,
    ShipmentStatus,
    SourceSystem,
    TransferStatus,
)
from app.db.facts import (
    InventorySnapshot,
    InventoryTransaction,
    PurchaseOrder,
    PurchaseOrderLine,
    SalesOrder,
    SalesOrderLine,
    Shipment,
    WarehouseTransfer,
)
from app.db.scheduling import (
    PurchaseOrderLifecycleEvent,
    SalesOrderLifecycleEvent,
    ScheduledTick,
)
from app.domain.scheduled_flow import (
    DEMAND_LOOKBACK_DAYS,
    SupplierCandidate,
    assign_supplier,
    carrier_actual_transit_days,
    is_below_reorder_point,
    jittered_lead_time_days,
    pick_demand_products,
    pick_demand_quantity,
    pick_requested_date_offset,
    pick_transfer_donor,
    reorder_quantity,
    roll_partial_receipt_fraction,
    transferable_surplus,
    warehouse_deficit,
)

logger = logging.getLogger(__name__)

REORDER_SAFETY_DAYS = 14  # matches Unit 10's low_stock_days_of_supply default
REORDER_TARGET_DAYS_OF_SUPPLY = 30
NEW_ORDER_PROBABILITY_PER_CUSTOMER = 0.15
GENERIC_PROMISE_DAYS = 2
# Warehouses have no carrier_id (internal move, not a Carrier-mediated
# shipment) -- PRD 3.1 calls a transfer "a lightweight operation between
# any two of the three warehouses", so a single fixed duration stands in
# for a per-pair distance model rather than inventing one from nothing.
WAREHOUSE_TRANSFER_TRANSIT_DAYS = 2


def _sim_datetime(simulation_date: date) -> datetime:
    return datetime.combine(simulation_date, time.min, tzinfo=timezone.utc)


def _current_inventory_position(session: Session, product_id: str, warehouse_id: str) -> int:
    total = session.execute(
        select(func.coalesce(func.sum(InventoryTransaction.quantity_delta), 0)).where(
            InventoryTransaction.product_id == product_id,
            InventoryTransaction.warehouse_id == warehouse_id,
        )
    ).scalar_one()
    return int(total)


def _avg_daily_shipped_demand(
    session: Session, product_id: str, warehouse_id: str, as_of: date
) -> float:
    window_start = _sim_datetime(as_of - timedelta(days=DEMAND_LOOKBACK_DAYS))
    total_shipped = session.execute(
        select(func.coalesce(func.sum(-InventoryTransaction.quantity_delta), 0)).where(
            InventoryTransaction.product_id == product_id,
            InventoryTransaction.warehouse_id == warehouse_id,
            InventoryTransaction.transaction_type == InventoryTransactionType.SHIPMENT,
            InventoryTransaction.transaction_at >= window_start,
        )
    ).scalar_one()
    return float(total_shipped) / DEMAND_LOOKBACK_DAYS


def _has_open_purchase_order(session: Session, product_id: str, warehouse_id: str) -> bool:
    open_statuses = (
        PurchaseOrderStatus.SUBMITTED,
        PurchaseOrderStatus.CONFIRMED,
        PurchaseOrderStatus.PARTIALLY_RECEIVED,
    )
    exists = session.execute(
        select(PurchaseOrderLine.id)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(
            PurchaseOrderLine.product_id == product_id,
            PurchaseOrder.warehouse_id == warehouse_id,
            PurchaseOrder.status.in_(open_statuses),
        )
        .limit(1)
    ).first()
    return exists is not None


def _has_open_inbound_transfer(session: Session, product_id: str, warehouse_id: str) -> bool:
    exists = session.execute(
        select(WarehouseTransfer.id)
        .where(
            WarehouseTransfer.product_id == product_id,
            WarehouseTransfer.to_warehouse_id == warehouse_id,
            WarehouseTransfer.status.in_((TransferStatus.PENDING, TransferStatus.IN_TRANSIT)),
        )
        .limit(1)
    ).first()
    return exists is not None


def _allocated_quantity(session: Session, product_id: str, warehouse_id: str) -> int:
    total = session.execute(
        select(
            func.coalesce(
                func.sum(SalesOrderLine.quantity_ordered - SalesOrderLine.quantity_shipped), 0
            )
        )
        .join(SalesOrder, SalesOrder.id == SalesOrderLine.sales_order_id)
        .where(
            SalesOrderLine.product_id == product_id,
            SalesOrder.warehouse_id == warehouse_id,
            SalesOrder.status.in_((SalesOrderStatus.ALLOCATED, SalesOrderStatus.PARTIALLY_SHIPPED)),
        )
    ).scalar_one()
    return int(total)


def _progress_purchase_orders(session: Session, simulation_date: date) -> int:
    events = 0
    open_pos = (
        session.execute(
            select(PurchaseOrder).where(
                PurchaseOrder.status.in_(
                    (
                        PurchaseOrderStatus.SUBMITTED,
                        PurchaseOrderStatus.CONFIRMED,
                        PurchaseOrderStatus.PARTIALLY_RECEIVED,
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    for po in open_pos:
        from_status = po.status
        if po.status == PurchaseOrderStatus.SUBMITTED:
            po.status = PurchaseOrderStatus.CONFIRMED
        elif simulation_date >= po.expected_delivery_date:
            lines = (
                session.execute(
                    select(PurchaseOrderLine).where(
                        PurchaseOrderLine.purchase_order_id == po.id
                    )
                )
                .scalars()
                .all()
            )
            # PRD 9.2 catalog row 4: re-rolled independently each tick
            # (keyed on this simulation_date + the PO's own id, same
            # reproducibility discipline as carrier_actual_transit_days) so
            # a PO that arrives short one day can still complete on a later
            # one without needing a second, separate roll mechanism.
            fraction = roll_partial_receipt_fraction(
                _rng(simulation_date, f"po_partial_receipt:{po.id}")
            )
            fully_received = True
            for line in lines:
                remaining = line.quantity_ordered - line.quantity_received
                if remaining <= 0:
                    continue
                receive_qty = remaining if fraction is None else max(1, int(remaining * fraction))
                receive_qty = min(receive_qty, remaining)
                if receive_qty < remaining:
                    fully_received = False
                session.add(
                    InventoryTransaction(
                        transaction_at=_sim_datetime(simulation_date),
                        product_id=line.product_id,
                        warehouse_id=po.warehouse_id,
                        transaction_type=InventoryTransactionType.RECEIPT,
                        quantity_delta=receive_qty,
                        reference_type="purchase_order",
                        reference_id=po.id,
                        source_system=SourceSystem.PROCUREMENT,
                    )
                )
                line.quantity_received += receive_qty
            po.status = (
                PurchaseOrderStatus.RECEIVED
                if fully_received
                else PurchaseOrderStatus.PARTIALLY_RECEIVED
            )
        else:
            continue
        if po.status == from_status:
            # A PO that rolls partial on two consecutive ticks
            # (PARTIALLY_RECEIVED -> PARTIALLY_RECEIVED) is real receiving
            # activity (already captured in the InventoryTransaction rows
            # above) but not a status *transition* -
            # PurchaseOrderLifecycleEvent is documented as recording
            # transitions, so logging a same-status row here would be
            # audit-trail noise and would inflate this tick's event count
            # for a tick that didn't actually change the PO's status.
            continue
        session.add(
            PurchaseOrderLifecycleEvent(
                purchase_order_id=po.id,
                from_status=from_status,
                to_status=po.status,
                simulation_date=simulation_date,
            )
        )
        events += 1
    session.flush()
    return events


def _create_purchase_orders_if_needed(session: Session, simulation_date: date) -> int:
    created = 0
    products = session.execute(select(Product).where(Product.is_active.is_(True))).scalars().all()
    warehouses = (
        session.execute(select(Warehouse).where(Warehouse.is_active.is_(True))).scalars().all()
    )
    suppliers = (
        session.execute(select(Supplier).where(Supplier.is_active.is_(True))).scalars().all()
    )
    supplier_candidates = [
        SupplierCandidate(id=s.id, category_focus=s.category_focus) for s in suppliers
    ]
    suppliers_by_id = {s.id: s for s in suppliers}

    for product in products:
        for warehouse in warehouses:
            if _has_open_purchase_order(
                session, product.id, warehouse.id
            ) or _has_open_inbound_transfer(session, product.id, warehouse.id):
                continue
            position = _current_inventory_position(session, product.id, warehouse.id)
            demand = _avg_daily_shipped_demand(session, product.id, warehouse.id, simulation_date)
            if not is_below_reorder_point(position, demand, REORDER_SAFETY_DAYS):
                continue
            supplier = suppliers_by_id[
                assign_supplier(product.category, supplier_candidates).id
            ]
            rng = _rng(simulation_date, f"procurement:{product.id}:{warehouse.id}")
            lead_time = jittered_lead_time_days(
                supplier.base_lead_time_days, supplier.lead_time_variability, rng
            )
            quantity = reorder_quantity(demand, REORDER_TARGET_DAYS_OF_SUPPLY)
            po = PurchaseOrder(
                po_number=f"PO-{uuid.uuid4().hex[:10].upper()}",
                supplier_id=supplier.id,
                warehouse_id=warehouse.id,
                order_date=simulation_date,
                expected_delivery_date=simulation_date + timedelta(days=lead_time),
                status=PurchaseOrderStatus.SUBMITTED,
                source_system=SourceSystem.PROCUREMENT,
            )
            session.add(po)
            session.flush()
            session.add(
                PurchaseOrderLine(
                    purchase_order_id=po.id,
                    product_id=product.id,
                    quantity_ordered=quantity,
                    quantity_received=0,
                    unit_cost=product.unit_cost,
                )
            )
            session.add(
                PurchaseOrderLifecycleEvent(
                    purchase_order_id=po.id,
                    from_status=None,
                    to_status=PurchaseOrderStatus.SUBMITTED,
                    simulation_date=simulation_date,
                )
            )
            created += 1
    return created


def _progress_warehouse_transfers(session: Session, simulation_date: date) -> int:
    events = 0
    in_flight = (
        session.execute(
            select(WarehouseTransfer).where(
                WarehouseTransfer.status.in_((TransferStatus.PENDING, TransferStatus.IN_TRANSIT))
            )
        )
        .scalars()
        .all()
    )
    for transfer in in_flight:
        if transfer.status == TransferStatus.PENDING:
            transfer.status = TransferStatus.IN_TRANSIT
            events += 1
        elif simulation_date >= transfer.transfer_date + timedelta(
            days=WAREHOUSE_TRANSFER_TRANSIT_DAYS
        ):
            transfer.status = TransferStatus.COMPLETED
            session.add(
                InventoryTransaction(
                    transaction_at=_sim_datetime(simulation_date),
                    product_id=transfer.product_id,
                    warehouse_id=transfer.to_warehouse_id,
                    transaction_type=InventoryTransactionType.TRANSFER_IN,
                    quantity_delta=transfer.quantity,
                    reference_type="warehouse_transfer",
                    reference_id=transfer.id,
                    source_system=SourceSystem.WMS,
                )
            )
            events += 1
    session.flush()
    return events


def _create_warehouse_transfers_if_needed(session: Session, simulation_date: date) -> int:
    created = 0
    products = session.execute(select(Product).where(Product.is_active.is_(True))).scalars().all()
    # Ordered explicitly: recipients are served against a shared,
    # per-product donor pool that's debited as each transfer is created
    # (see positions[donor_id] below), so which recipient goes first is
    # outcome-relevant here in a way it wasn't for the PO loop above.
    # Without an ORDER BY that resolution order is whatever Postgres
    # happens to return it in — unspecified, and not something a tick's
    # reproducibility should depend on.
    warehouses = (
        session.execute(
            select(Warehouse).where(Warehouse.is_active.is_(True)).order_by(Warehouse.id)
        )
        .scalars()
        .all()
    )
    for product in products:
        # Local, per-product snapshot: a donor's position is debited here
        # (not written to the DB until the InventoryTransaction below) so a
        # second recipient warehouse considered later in this same loop
        # sees the donor's already-committed-this-tick surplus, not the
        # stale pre-tick figure — otherwise two recipients could both be
        # sized against the same surplus and jointly overdraw the donor.
        positions = {
            w.id: _current_inventory_position(session, product.id, w.id) for w in warehouses
        }
        allocated = {w.id: _allocated_quantity(session, product.id, w.id) for w in warehouses}
        demands = {
            w.id: _avg_daily_shipped_demand(session, product.id, w.id, simulation_date)
            for w in warehouses
        }
        for warehouse in warehouses:
            if _has_open_purchase_order(
                session, product.id, warehouse.id
            ) or _has_open_inbound_transfer(session, product.id, warehouse.id):
                continue
            deficit = warehouse_deficit(
                positions[warehouse.id], demands[warehouse.id], REORDER_SAFETY_DAYS
            )
            if deficit <= 0:
                continue
            candidates = [
                (
                    donor.id,
                    transferable_surplus(
                        positions[donor.id],
                        allocated[donor.id],
                        demands[donor.id],
                        REORDER_SAFETY_DAYS,
                    ),
                )
                for donor in warehouses
                if donor.id != warehouse.id
            ]
            picked = pick_transfer_donor(candidates)
            if picked is None:
                continue
            donor_id, donor_surplus = picked
            quantity = min(deficit, donor_surplus)
            if quantity <= 0:
                continue
            transfer = WarehouseTransfer(
                product_id=product.id,
                from_warehouse_id=donor_id,
                to_warehouse_id=warehouse.id,
                quantity=quantity,
                transfer_date=simulation_date,
                status=TransferStatus.PENDING,
                source_system=SourceSystem.WMS,
            )
            session.add(transfer)
            session.flush()
            session.add(
                InventoryTransaction(
                    transaction_at=_sim_datetime(simulation_date),
                    product_id=product.id,
                    warehouse_id=donor_id,
                    transaction_type=InventoryTransactionType.TRANSFER_OUT,
                    quantity_delta=-quantity,
                    reference_type="warehouse_transfer",
                    reference_id=transfer.id,
                    source_system=SourceSystem.WMS,
                )
            )
            positions[donor_id] -= quantity
            created += 1
    return created


def _rng(simulation_date: date, purpose: str) -> random.Random:
    return random.Random(f"{simulation_date.isoformat()}:{purpose}")


def _pick_carrier(carriers: list[Carrier], sales_order_id: uuid.UUID) -> Carrier:
    ordered = sorted(carriers, key=lambda c: c.id)
    return ordered[sales_order_id.int % len(ordered)]


def _progress_sales_orders_and_shipments(session: Session, simulation_date: date) -> int:
    # Progress shipments created on earlier ticks BEFORE this tick creates
    # any new ones — otherwise a shipment just created below (status
    # PENDING) would be immediately swept up and advanced to IN_TRANSIT in
    # the same pass it was created in.
    events = _progress_shipments(session, simulation_date)
    open_sos = (
        session.execute(
            select(SalesOrder).where(
                SalesOrder.status.in_(
                    (
                        SalesOrderStatus.SUBMITTED,
                        SalesOrderStatus.ALLOCATED,
                        SalesOrderStatus.PARTIALLY_SHIPPED,
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    carriers = session.execute(select(Carrier).where(Carrier.is_active.is_(True))).scalars().all()

    for so in open_sos:
        from_status = so.status
        lines = (
            session.execute(select(SalesOrderLine).where(SalesOrderLine.sales_order_id == so.id))
            .scalars()
            .all()
        )
        if so.status == SalesOrderStatus.SUBMITTED:
            all_available = all(
                _current_inventory_position(session, line.product_id, so.warehouse_id)
                >= (line.quantity_ordered - line.quantity_shipped)
                for line in lines
            )
            if not all_available:
                continue
            so.status = SalesOrderStatus.ALLOCATED
            so.promised_date = simulation_date + timedelta(days=GENERIC_PROMISE_DAYS)
            session.add(
                SalesOrderLifecycleEvent(
                    sales_order_id=so.id,
                    from_status=from_status,
                    to_status=so.status,
                    simulation_date=simulation_date,
                )
            )
            events += 1
            continue

        shipped_any_line = False
        for line in lines:
            remaining = line.quantity_ordered - line.quantity_shipped
            if remaining <= 0:
                continue
            position = _current_inventory_position(session, line.product_id, so.warehouse_id)
            if position < remaining:
                continue
            session.add(
                InventoryTransaction(
                    transaction_at=_sim_datetime(simulation_date),
                    product_id=line.product_id,
                    warehouse_id=so.warehouse_id,
                    transaction_type=InventoryTransactionType.SHIPMENT,
                    quantity_delta=-remaining,
                    reference_type="sales_order",
                    reference_id=so.id,
                    source_system=SourceSystem.WMS,
                )
            )
            line.quantity_shipped = line.quantity_ordered
            shipped_any_line = True

        if not shipped_any_line:
            continue

        fully_shipped = all(line.quantity_shipped >= line.quantity_ordered for line in lines)
        so.status = (
            SalesOrderStatus.SHIPPED if fully_shipped else SalesOrderStatus.PARTIALLY_SHIPPED
        )
        if fully_shipped and carriers:
            carrier = _pick_carrier(carriers, so.id)
            transit_days = round(
                (float(carrier.transit_days_min) + float(carrier.transit_days_max)) / 2
            )
            session.add(
                Shipment(
                    sales_order_id=so.id,
                    carrier_id=carrier.id,
                    warehouse_id=so.warehouse_id,
                    ship_date=simulation_date,
                    promised_delivery_date=simulation_date + timedelta(days=transit_days),
                    status=ShipmentStatus.PENDING,
                    source_system=SourceSystem.WMS,
                )
            )
        if from_status != so.status:
            session.add(
                SalesOrderLifecycleEvent(
                    sales_order_id=so.id,
                    from_status=from_status,
                    to_status=so.status,
                    simulation_date=simulation_date,
                )
            )
            events += 1

    session.flush()
    return events


def _progress_shipments(session: Session, simulation_date: date) -> int:
    progressed = 0
    in_flight = (
        session.execute(
            select(Shipment).where(
                Shipment.status.in_((ShipmentStatus.PENDING, ShipmentStatus.IN_TRANSIT))
            )
        )
        .scalars()
        .all()
    )
    for shipment in in_flight:
        if shipment.status == ShipmentStatus.PENDING:
            shipment.status = ShipmentStatus.IN_TRANSIT
            progressed += 1
            continue
        carrier = session.get(Carrier, shipment.carrier_id)
        promised_transit_days = (shipment.promised_delivery_date - shipment.ship_date).days
        rng = _rng(shipment.ship_date, f"carrier_transit:{shipment.id}")
        actual_transit_days = carrier_actual_transit_days(
            promised_transit_days, carrier.variability, float(carrier.reliability_pct), rng
        )
        actual_delivery_date = shipment.ship_date + timedelta(days=actual_transit_days)
        if simulation_date >= actual_delivery_date:
            shipment.status = ShipmentStatus.DELIVERED
            shipment.actual_delivery_date = actual_delivery_date
            progressed += 1
    return progressed


def _create_sales_orders_if_needed(session: Session, simulation_date: date) -> int:
    created = 0
    customers = (
        session.execute(select(Customer).where(Customer.is_active.is_(True))).scalars().all()
    )
    products = (
        session.execute(select(Product.id).where(Product.is_active.is_(True))).scalars().all()
    )
    for customer in customers:
        rng = _rng(simulation_date, f"demand:{customer.id}")
        if rng.random() >= NEW_ORDER_PROBABILITY_PER_CUSTOMER:
            continue
        chosen_products = pick_demand_products(rng, list(products))
        if not chosen_products:
            continue
        so = SalesOrder(
            so_number=f"SO-{uuid.uuid4().hex[:10].upper()}",
            customer_id=customer.id,
            warehouse_id=customer.warehouse_id,
            order_date=simulation_date,
            requested_date=simulation_date + timedelta(days=pick_requested_date_offset(rng)),
            status=SalesOrderStatus.SUBMITTED,
            source_system=SourceSystem.ERP,
        )
        session.add(so)
        session.flush()
        for product_id in chosen_products:
            product = session.get(Product, product_id)
            session.add(
                SalesOrderLine(
                    sales_order_id=so.id,
                    product_id=product_id,
                    quantity_ordered=pick_demand_quantity(rng),
                    quantity_shipped=0,
                    unit_price=float(product.unit_cost) * 1.4,
                )
            )
        session.add(
            SalesOrderLifecycleEvent(
                sales_order_id=so.id,
                from_status=None,
                to_status=SalesOrderStatus.SUBMITTED,
                simulation_date=simulation_date,
            )
        )
        created += 1
    return created


def _snapshot_inventory_positions(session: Session, simulation_date: date) -> None:
    """Writes one InventorySnapshot row per (product, warehouse): on-hand
    quantity derived from the transaction ledger, allocated quantity from
    open (ALLOCATED/PARTIALLY_SHIPPED) sales-order lines — upserted per
    day via the table's own unique constraint, so a re-run of the same day
    replaces rather than duplicates.

    Found while building Unit 14's KPI engine: sql/kpi/days_of_supply.sql
    (Unit 10) reads inventory_snapshot, not inventory_transaction directly
    — nothing wrote to it until this fix, so that KPI was always NULL.
    Fixed here rather than in the KPI engine itself, since a daily
    inventory-position rollup is this unit's natural responsibility (it
    already computes _current_inventory_position for its own reorder
    logic), not a KPI-computation concern.

    Uses one GROUP BY query for positions rather than a per-pair call
    (security review, LOW — the original per-pair-call version issued ~60
    queries per tick on the seeded baseline)."""
    products = (
        session.execute(select(Product.id).where(Product.is_active.is_(True))).scalars().all()
    )
    warehouses = (
        session.execute(select(Warehouse.id).where(Warehouse.is_active.is_(True))).scalars().all()
    )
    position_rows = session.execute(
        select(
            InventoryTransaction.product_id,
            InventoryTransaction.warehouse_id,
            func.sum(InventoryTransaction.quantity_delta).label("position"),
        ).group_by(InventoryTransaction.product_id, InventoryTransaction.warehouse_id)
    ).all()
    position_by_key = {(r.product_id, r.warehouse_id): int(r.position) for r in position_rows}
    allocated_rows = session.execute(
        select(
            SalesOrderLine.product_id,
            SalesOrder.warehouse_id,
            func.sum(SalesOrderLine.quantity_ordered - SalesOrderLine.quantity_shipped).label(
                "allocated"
            ),
        )
        .join(SalesOrder, SalesOrder.id == SalesOrderLine.sales_order_id)
        .where(
            SalesOrder.status.in_(
                (SalesOrderStatus.ALLOCATED, SalesOrderStatus.PARTIALLY_SHIPPED)
            )
        )
        .group_by(SalesOrderLine.product_id, SalesOrder.warehouse_id)
    ).all()
    allocated_by_key = {(r.product_id, r.warehouse_id): int(r.allocated) for r in allocated_rows}

    values = []
    for product_id in products:
        for warehouse_id in warehouses:
            position = position_by_key.get((product_id, warehouse_id), 0)
            if position < 0:
                # Should be unreachable — _progress_sales_orders_and_shipments
                # never ships more than is on hand — but the table's own
                # quantity_on_hand >= 0 CHECK constraint (facts.py) requires
                # clamping regardless. Logged, not silently swallowed, so a
                # future bug (e.g. Unit 17's short-receipt/damage scenarios)
                # surfaces instead of vanishing into a floored 0.
                logger.warning(
                    "negative inventory position for product=%s warehouse=%s on %s: %d "
                    "(clamped to 0)",
                    product_id,
                    warehouse_id,
                    simulation_date,
                    position,
                )
            values.append(
                {
                    "snapshot_date": simulation_date,
                    "product_id": product_id,
                    "warehouse_id": warehouse_id,
                    "quantity_on_hand": max(position, 0),
                    "quantity_allocated": max(
                        allocated_by_key.get((product_id, warehouse_id), 0), 0
                    ),
                    "source_system": SourceSystem.WMS,
                }
            )
    if not values:
        return
    stmt = pg_insert(InventorySnapshot).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["snapshot_date", "product_id", "warehouse_id"],
        set_={
            "quantity_on_hand": stmt.excluded.quantity_on_hand,
            "quantity_allocated": stmt.excluded.quantity_allocated,
        },
    )
    session.execute(stmt)


def run_scheduled_tick(session: Session, simulation_date: date) -> ScheduledTick:
    """Runs one full pass of the procure-to-stock/order-to-ship flow for
    simulation_date. Does not commit — matches simulation_clock_ops's
    caller-owns-the-transaction convention. Always writes exactly one
    ScheduledTick row: SUCCESS with the real event count on a clean run,
    or FAILED (0 events) with the original exception re-raised so the
    caller still sees the failure.

    security review: a DB-level exception (IntegrityError, etc.) leaves the
    session in "pending rollback" state — writing the FAILED row directly
    into that state would itself raise PendingRollbackError, masking the
    original exception and losing the very audit row this is meant to
    preserve. session.rollback() first clears that state (also discarding
    any partial progress from earlier in this same call — an accepted
    tradeoff for the DB-error case; the pure-Python-exception case, which
    never dirties the session's transactional state, loses nothing it
    wouldn't have lost anyway)."""
    try:
        events = 0
        events += _progress_purchase_orders(session, simulation_date)
        events += _progress_warehouse_transfers(session, simulation_date)
        events += _create_warehouse_transfers_if_needed(session, simulation_date)
        events += _create_purchase_orders_if_needed(session, simulation_date)
        events += _progress_sales_orders_and_shipments(session, simulation_date)
        events += _create_sales_orders_if_needed(session, simulation_date)
        _snapshot_inventory_positions(session, simulation_date)
    except Exception:
        session.rollback()
        tick = ScheduledTick(
            simulation_date=simulation_date,
            events_generated=0,
            status=ScheduledTickStatus.FAILED,
        )
        session.add(tick)
        session.flush()
        raise
    tick = ScheduledTick(
        simulation_date=simulation_date,
        events_generated=events,
        status=ScheduledTickStatus.SUCCESS,
    )
    session.add(tick)
    session.flush()
    return tick
