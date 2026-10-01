"""Unit 41 (MEADOWOPS-DOM-029): the Overview page's aggregates. Each test
works in one rolled-back transaction on a world wiped of generated data, with
hand-built facts, so every expected number is known exactly."""

import os
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from app.db.dimensions import Customer, Product, Supplier, Warehouse
from app.db.enums import (
    PurchaseOrderStatus,
    SalesOrderStatus,
    ShipmentStatus,
    SourceSystem,
)
from app.db.exception_flags import ExceptionFlag
from app.db.facts import (
    InventorySnapshot,
    PurchaseOrder,
    PurchaseOrderLine,
    SalesOrder,
    SalesOrderLine,
    Shipment,
)
from app.db.dimensions import Carrier
from app.db.kpi import DaysOfSupplySnapshot, KpiSnapshot
from app.db.enums import ScheduledTickStatus
from app.db.scheduling import PurchaseOrderLifecycleEvent, ScheduledTick
from app.db.world_state import SimulationClock
from app.services.baseline_data import seed_master_data
from app.services.dashboard_overview import build_overview
from app.services.exception_rule_defaults import seed_exception_rule_thresholds
from app.services.simulation_clock_ops import seed_initial_world_state_and_clock
from app.services.world_repopulate import GENERATED_TABLES

_AS_OF = date(2026, 9, 20)
_DAYS = 7  # window 2026-09-14 .. 2026-09-20


def _d(offset: int) -> date:
    """Day `offset` of the window: 0 is its first day, _DAYS - 1 is as-of."""
    return _AS_OF - timedelta(days=_DAYS - 1 - offset)


@pytest.fixture
def session():
    engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
    with Session(engine) as session:
        seed_master_data(session)
        seed_exception_rule_thresholds(session)
        seed_initial_world_state_and_clock(session)
        session.commit()
        for model in GENERATED_TABLES:
            session.execute(delete(model))
        clock = session.get(SimulationClock, 1)
        clock.simulation_date = _AS_OF
        session.flush()
        yield session
        session.rollback()
    engine.dispose()


@pytest.fixture
def customer(session: Session) -> Customer:
    return session.scalars(select(Customer).order_by(Customer.id)).first()


@pytest.fixture
def carrier(session: Session) -> Carrier:
    return session.scalars(select(Carrier).order_by(Carrier.id)).first()


def _sales_order(
    session: Session,
    customer: Customer,
    *,
    order_date: date,
    status: SalesOrderStatus = SalesOrderStatus.SUBMITTED,
    lines: tuple[tuple[str, int, int, str], ...] = (),
) -> SalesOrder:
    """lines: (product_id, quantity_ordered, quantity_shipped, unit_price)"""
    order = SalesOrder(
        so_number=f"SO-ZZ{uuid.uuid4().hex[:8].upper()}",
        customer_id=customer.id,
        warehouse_id=customer.warehouse_id,
        order_date=order_date,
        requested_date=order_date + timedelta(days=3),
        status=status,
        source_system=SourceSystem.ERP,
    )
    session.add(order)
    session.flush()
    for product_id, ordered, shipped, price in lines:
        session.add(
            SalesOrderLine(
                sales_order_id=order.id,
                product_id=product_id,
                quantity_ordered=ordered,
                quantity_shipped=shipped,
                unit_price=Decimal(price),
            )
        )
    session.flush()
    return order


def _shipment(
    session: Session,
    order: SalesOrder,
    carrier: Carrier,
    *,
    ship_date: date,
    promised: date,
    delivered: date | None,
    status: ShipmentStatus,
) -> Shipment:
    shipment = Shipment(
        sales_order_id=order.id,
        carrier_id=carrier.id,
        warehouse_id=order.warehouse_id,
        ship_date=ship_date,
        promised_delivery_date=promised,
        actual_delivery_date=delivered,
        status=status,
        source_system=SourceSystem.WMS,
    )
    session.add(shipment)
    session.flush()
    return shipment


class TestEmptyWorld:
    def test_every_window_day_is_present_with_zeros(self, session: Session) -> None:
        overview = build_overview(session, days=_DAYS)

        assert overview.as_of == _AS_OF
        assert overview.window_start == _d(0)
        assert overview.window_days == _DAYS
        assert [row.simulation_date for row in overview.daily_activity] == [
            _d(n) for n in range(_DAYS)
        ]
        assert all(
            row.orders_placed == row.shipments_shipped == row.delivered_late == 0
            and row.order_value == 0
            for row in overview.daily_activity
        )
        assert overview.kpi_trend == []
        assert overview.sales_order_status == []
        assert overview.top_products == []
        assert overview.shipment_delivery.model_dump() == {
            "delivered_on_time": 0, "delivered_late": 0, "in_progress": 0, "exception": 0
        }

    def test_every_active_warehouse_is_listed_even_with_no_stock(self, session: Session) -> None:
        overview = build_overview(session, days=_DAYS)

        ids = {w.warehouse_id for w in overview.inventory_by_warehouse}
        expected = set(session.scalars(select(Warehouse.id).where(Warehouse.is_active.is_(True))))
        assert ids == expected
        assert all(w.units_on_hand == 0 for w in overview.inventory_by_warehouse)


class TestWindowStartsWhereDataStarts:
    """Days before the simulation had any recorded activity are not "zero
    orders" - there was no data - so the window never reaches back past the
    first recorded day instead of drawing them as flat zeros."""

    def _tick(self, session: Session, day: date) -> None:
        session.add(
            ScheduledTick(
                simulation_date=day, events_generated=1, status=ScheduledTickStatus.SUCCESS
            )
        )

    def test_the_window_is_clamped_to_the_first_recorded_day(self, session: Session) -> None:
        for offset in (4, 5, 6):
            self._tick(session, _d(offset))
        session.flush()

        overview = build_overview(session, days=_DAYS)

        assert overview.window_start == _d(4)
        assert overview.window_days == 3
        assert [r.simulation_date for r in overview.daily_activity] == [_d(4), _d(5), _d(6)]
        assert len(overview.new_exceptions_per_day) == 3

    def test_history_longer_than_the_window_leaves_it_unchanged(self, session: Session) -> None:
        for offset in range(-3, _DAYS):
            self._tick(session, _d(0) + timedelta(days=offset))
        session.flush()

        overview = build_overview(session, days=_DAYS)

        assert overview.window_start == _d(0)
        assert overview.window_days == _DAYS


class TestOrders:
    def test_only_orders_inside_the_window_count(
        self, session: Session, customer: Customer
    ) -> None:
        _sales_order(session, customer, order_date=_d(0))
        _sales_order(session, customer, order_date=_d(0))
        _sales_order(session, customer, order_date=_d(3))
        _sales_order(session, customer, order_date=_d(0) - timedelta(days=1))  # before

        overview = build_overview(session, days=_DAYS)

        placed = {r.simulation_date: r.orders_placed for r in overview.daily_activity}
        assert placed[_d(0)] == 2
        assert placed[_d(3)] == 1
        assert sum(placed.values()) == 3

    def test_order_value_is_quantity_times_price(
        self, session: Session, customer: Customer
    ) -> None:
        _sales_order(
            session, customer, order_date=_d(2),
            lines=(("SKU-COR-001", 10, 0, "2.50"), ("SKU-COR-002", 4, 0, "5.00")),
        )

        overview = build_overview(session, days=_DAYS)

        day = next(r for r in overview.daily_activity if r.simulation_date == _d(2))
        assert day.order_value == Decimal("45.00")

    def test_orders_are_counted_by_status(self, session: Session, customer: Customer) -> None:
        _sales_order(session, customer, order_date=_d(1), status=SalesOrderStatus.SHIPPED)
        _sales_order(session, customer, order_date=_d(1), status=SalesOrderStatus.SHIPPED)
        _sales_order(session, customer, order_date=_d(2), status=SalesOrderStatus.ALLOCATED)

        overview = build_overview(session, days=_DAYS)

        assert {(c.label, c.count) for c in overview.sales_order_status} == {
            ("shipped", 2), ("allocated", 1)
        }

    def test_top_products_rank_by_units_ordered(
        self, session: Session, customer: Customer
    ) -> None:
        _sales_order(
            session, customer, order_date=_d(1),
            lines=(("SKU-COR-001", 5, 5, "1.00"), ("SKU-COR-002", 30, 12, "1.00")),
        )
        _sales_order(
            session, customer, order_date=_d(2), lines=(("SKU-COR-001", 20, 10, "1.00"),),
        )

        overview = build_overview(session, days=_DAYS)

        top = [(p.product_id, p.units_ordered, p.units_shipped) for p in overview.top_products]
        assert top == [("SKU-COR-002", 30, 12), ("SKU-COR-001", 25, 15)]
        assert overview.top_products[0].product_name


class TestShipments:
    def test_deliveries_split_into_on_time_and_late(
        self, session: Session, customer: Customer, carrier: Carrier
    ) -> None:
        order = _sales_order(session, customer, order_date=_d(0))
        _shipment(session, order, carrier, ship_date=_d(1), promised=_d(4), delivered=_d(4),
                  status=ShipmentStatus.DELIVERED)  # on the promised day: on time
        _shipment(session, order, carrier, ship_date=_d(1), promised=_d(3), delivered=_d(5),
                  status=ShipmentStatus.DELIVERED)  # two days late
        _shipment(session, order, carrier, ship_date=_d(2), promised=_d(6), delivered=None,
                  status=ShipmentStatus.IN_TRANSIT)
        _shipment(session, order, carrier, ship_date=_d(2), promised=_d(6), delivered=None,
                  status=ShipmentStatus.EXCEPTION)

        overview = build_overview(session, days=_DAYS)

        assert overview.shipment_delivery.model_dump() == {
            "delivered_on_time": 1, "delivered_late": 1, "in_progress": 1, "exception": 1
        }
        by_day = {r.simulation_date: r for r in overview.daily_activity}
        assert by_day[_d(4)].delivered_on_time == 1
        assert by_day[_d(5)].delivered_late == 1
        assert by_day[_d(1)].shipments_shipped == 2
        assert by_day[_d(2)].shipments_shipped == 2


class TestInventory:
    def test_uses_the_latest_snapshot_per_warehouse(self, session: Session) -> None:
        warehouse = session.scalars(select(Warehouse).order_by(Warehouse.id)).first()
        for snap_date, on_hand, allocated in ((_d(0), 999, 999), (_d(5), 120, 30)):
            session.add(
                InventorySnapshot(
                    snapshot_date=snap_date, product_id="SKU-COR-001",
                    warehouse_id=warehouse.id, quantity_on_hand=on_hand,
                    quantity_allocated=allocated, source_system=SourceSystem.WMS,
                )
            )
        session.add(
            InventorySnapshot(
                snapshot_date=_d(5), product_id="SKU-COR-002", warehouse_id=warehouse.id,
                quantity_on_hand=80, quantity_allocated=0, source_system=SourceSystem.WMS,
            )
        )
        session.flush()

        overview = build_overview(session, days=_DAYS)

        row = next(w for w in overview.inventory_by_warehouse if w.warehouse_id == warehouse.id)
        assert (row.units_on_hand, row.units_allocated) == (200, 30)

    def test_averages_the_latest_days_of_supply_and_counts_low_stock(
        self, session: Session
    ) -> None:
        warehouse = session.scalars(select(Warehouse).order_by(Warehouse.id)).first()
        for sku, days in (("SKU-COR-001", "10.0"), ("SKU-COR-002", "20.0")):
            session.add(
                DaysOfSupplySnapshot(
                    simulation_date=_d(6), product_id=sku, warehouse_id=warehouse.id,
                    days_of_supply=Decimal(days),
                )
            )
        session.add(
            DaysOfSupplySnapshot(
                simulation_date=_d(1), product_id="SKU-COR-001", warehouse_id=warehouse.id,
                days_of_supply=Decimal("1.0"),
            )
        )
        session.add(
            ExceptionFlag(
                category="low_stock_days_of_supply", product_id="SKU-COR-001",
                warehouse_id=warehouse.id, simulation_date=_d(6),
                first_detected_simulation_date=_d(6), measured_value=Decimal("4"),
                threshold_value=Decimal("14"),
            )
        )
        session.flush()

        overview = build_overview(session, days=_DAYS)

        row = next(w for w in overview.inventory_by_warehouse if w.warehouse_id == warehouse.id)
        assert row.avg_days_of_supply == Decimal("15.0")
        assert row.low_stock_positions == 1


class TestSuppliers:
    def _purchase_order(
        self, session: Session, supplier: Supplier, *, order_date: date, expected: date,
        status: PurchaseOrderStatus, received_on: date | None,
    ) -> PurchaseOrder:
        warehouse_id = session.scalars(select(Warehouse.id).order_by(Warehouse.id)).first()
        po = PurchaseOrder(
            po_number=f"PO-ZZ{uuid.uuid4().hex[:8].upper()}", supplier_id=supplier.id,
            warehouse_id=warehouse_id, order_date=order_date, expected_delivery_date=expected,
            status=status, source_system=SourceSystem.PROCUREMENT,
        )
        session.add(po)
        session.flush()
        session.add(
            PurchaseOrderLine(
                purchase_order_id=po.id, product_id="SKU-COR-001", quantity_ordered=10,
                quantity_received=10 if received_on else 0, unit_cost=Decimal("1.00"),
            )
        )
        if received_on is not None:
            session.add(
                PurchaseOrderLifecycleEvent(
                    purchase_order_id=po.id, from_status=PurchaseOrderStatus.CONFIRMED,
                    to_status=PurchaseOrderStatus.RECEIVED, simulation_date=received_on,
                )
            )
        session.flush()
        return po

    def test_on_time_receipt_rate(self, session: Session) -> None:
        supplier = session.scalars(select(Supplier).order_by(Supplier.id)).first()
        received = PurchaseOrderStatus.RECEIVED
        self._purchase_order(session, supplier, order_date=_d(0), expected=_d(3),
                             status=received, received_on=_d(2))   # early: on time
        self._purchase_order(session, supplier, order_date=_d(0), expected=_d(3),
                             status=received, received_on=_d(3))   # on the day: on time
        self._purchase_order(session, supplier, order_date=_d(0), expected=_d(3),
                             status=received, received_on=_d(5))   # late
        self._purchase_order(session, supplier, order_date=_d(1), expected=_d(9),
                             status=PurchaseOrderStatus.SUBMITTED, received_on=None)

        overview = build_overview(session, days=_DAYS)

        row = next(s for s in overview.suppliers if s.supplier_id == supplier.id)
        assert row.purchase_orders_placed == 4
        assert row.purchase_orders_received == 3
        assert row.received_on_time == 2
        assert row.on_time_receipt_pct == Decimal("66.7")
        assert row.open_purchase_orders == 1

    def test_a_supplier_with_nothing_received_has_no_rate(self, session: Session) -> None:
        overview = build_overview(session, days=_DAYS)

        assert overview.suppliers
        assert all(s.on_time_receipt_pct is None for s in overview.suppliers)


class TestExceptionsAndKpis:
    def test_open_exceptions_by_category_and_new_per_day(self, session: Session) -> None:
        def flag(category: str, sku: str, detected: date, resolved: bool = False) -> ExceptionFlag:
            from datetime import datetime, timezone

            return ExceptionFlag(
                category=category, product_id=sku, warehouse_id="WH-EAST",
                simulation_date=detected, first_detected_simulation_date=detected,
                measured_value=Decimal("1"), threshold_value=Decimal("2"),
                resolved_at=datetime.now(timezone.utc) if resolved else None,
            )

        session.add_all([
            flag("low_stock_days_of_supply", "SKU-COR-001", _d(2)),
            flag("low_stock_days_of_supply", "SKU-COR-002", _d(2)),
            flag("low_stock_days_of_supply", "SKU-COR-003", _d(4), resolved=True),
            flag("low_stock_days_of_supply", "SKU-COR-004", _d(0) - timedelta(days=5)),
        ])
        session.flush()

        overview = build_overview(session, days=_DAYS)

        open_counts = {c.category: c.open_count for c in overview.open_exceptions_by_category}
        assert open_counts == {"low_stock_days_of_supply": 3}
        new_by_day = {r.simulation_date: r.count for r in overview.new_exceptions_per_day}
        assert new_by_day[_d(2)] == 2
        assert new_by_day[_d(4)] == 1  # resolved flags were still detected that day
        assert sum(new_by_day.values()) == 3
        assert len(overview.new_exceptions_per_day) == _DAYS

    def test_kpi_trend_is_the_windowed_snapshots_in_date_order(self, session: Session) -> None:
        for offset, otif in ((4, "90.0"), (1, "80.0"), (-3, "10.0")):
            session.add(
                KpiSnapshot(
                    simulation_date=_d(0) + timedelta(days=offset), otif_pct=Decimal(otif),
                    fill_rate_pct=Decimal("95.0"), order_cycle_time_days=Decimal("2.0"),
                    perfect_order_rate_pct=Decimal("85.0"),
                )
            )
        session.flush()

        overview = build_overview(session, days=_DAYS)

        assert [(p.simulation_date, p.otif_pct) for p in overview.kpi_trend] == [
            (_d(1), Decimal("80.0")), (_d(4), Decimal("90.0"))
        ]
