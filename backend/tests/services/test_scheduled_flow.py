"""Unit 13 (MEADOWOPS-DOM-006): scheduled procure-to-stock/order-to-ship
flow, transactional layer. Runs against the real seeded baseline data
(Unit 5) inside an uncommitted transaction per test — same non-autocommit
discipline as every other DB test in this suite (Units 2/3/4/5/10/12a):
nothing here is ever left committed, via Session.close()'s implicit
rollback.

Unit 27 (MEADOWOPS-DOM-021, business id MEADOWOPS-DOMAIN-016, PRD 3.4/5.2)
adds warehouse-to-warehouse transfer creation/progression and
carrier-variability shipment-lateness tests to this same module.
"""

import os
import random
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.dimensions import Carrier
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
from app.domain.scheduled_flow import carrier_actual_transit_days
from app.services.baseline_data import seed_master_data
from app.services.scheduled_flow import (
    WAREHOUSE_TRANSFER_TRANSIT_DAYS,
    _create_purchase_orders_if_needed,
    _create_sales_orders_if_needed,
    _create_warehouse_transfers_if_needed,
    _current_inventory_position,
    _progress_purchase_orders,
    _progress_sales_orders_and_shipments,
    _progress_warehouse_transfers,
    _snapshot_inventory_positions,
    run_scheduled_tick,
)

SIM_DATE = date(2026, 3, 2)

# Real seeded baseline (Unit 5): SKU-COR-001 is corrugated_packaging, its
# assigned supplier resolves to S-001 (lowest-id keyword match on
# "corrugated" — see TestAssignSupplier in tests/domain).
_PRODUCT_ID = "SKU-COR-001"
_WAREHOUSE_ID = "WH-EAST"
_OTHER_WAREHOUSE_ID = "WH-CENTRAL"
_THIRD_WAREHOUSE_ID = "WH-WEST"
_SUPPLIER_ID = "S-001"
_CUSTOMER_ID = "CUST-EAST-01"


@pytest.fixture
def session():
    engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
    with Session(engine) as session:
        seed_master_data(session)
        session.commit()  # baseline is idempotent (ON CONFLICT DO NOTHING) — safe to commit
        yield session
        session.rollback()
    engine.dispose()


def _seed_receipt(session: Session, quantity: int, *, days_ago: int = 0) -> None:
    _seed_receipt_at(session, _WAREHOUSE_ID, quantity, days_ago=days_ago)


def _seed_receipt_at(
    session: Session, warehouse_id: str, quantity: int, *, days_ago: int = 0
) -> None:
    session.add(
        InventoryTransaction(
            transaction_at=SIM_DATE - timedelta(days=days_ago),
            product_id=_PRODUCT_ID,
            warehouse_id=warehouse_id,
            transaction_type="receipt",
            quantity_delta=quantity,
            source_system=SourceSystem.PROCUREMENT,
        )
    )
    session.flush()


def _insert_so(session: Session, *, quantity_ordered: int) -> SalesOrder:
    so = SalesOrder(
        so_number=f"SO-TEST-{uuid.uuid4().hex[:8]}",
        customer_id=_CUSTOMER_ID,
        warehouse_id=_WAREHOUSE_ID,
        order_date=SIM_DATE,
        requested_date=SIM_DATE + timedelta(days=2),
        status=SalesOrderStatus.SUBMITTED,
        source_system=SourceSystem.ERP,
    )
    session.add(so)
    session.flush()
    session.add(
        SalesOrderLine(
            sales_order_id=so.id,
            product_id=_PRODUCT_ID,
            quantity_ordered=quantity_ordered,
            quantity_shipped=0,
            unit_price=1.5,
        )
    )
    session.flush()
    return so


class TestCreatePurchaseOrdersIfNeeded:
    def test_creates_a_po_for_a_product_with_zero_position_and_zero_demand(
        self, session: Session
    ) -> None:
        _create_purchase_orders_if_needed(session, SIM_DATE)
        po = session.execute(
            select(PurchaseOrder)
            .join(PurchaseOrderLine, PurchaseOrderLine.purchase_order_id == PurchaseOrder.id)
            .where(
                PurchaseOrderLine.product_id == _PRODUCT_ID,
                PurchaseOrder.warehouse_id == _WAREHOUSE_ID,
            )
        ).scalar_one_or_none()
        assert po is not None
        assert po.supplier_id == _SUPPLIER_ID
        assert po.status == PurchaseOrderStatus.SUBMITTED

    def test_records_a_creation_lifecycle_event_with_null_from_status(
        self, session: Session
    ) -> None:
        _create_purchase_orders_if_needed(session, SIM_DATE)
        po = session.execute(
            select(PurchaseOrder)
            .join(PurchaseOrderLine, PurchaseOrderLine.purchase_order_id == PurchaseOrder.id)
            .where(
                PurchaseOrderLine.product_id == _PRODUCT_ID,
                PurchaseOrder.warehouse_id == _WAREHOUSE_ID,
            )
        ).scalar_one()
        event = session.execute(
            select(PurchaseOrderLifecycleEvent).where(
                PurchaseOrderLifecycleEvent.purchase_order_id == po.id
            )
        ).scalar_one()
        assert event.from_status is None
        assert event.to_status == PurchaseOrderStatus.SUBMITTED

    def test_does_not_create_a_second_po_while_one_is_already_open(
        self, session: Session
    ) -> None:
        _create_purchase_orders_if_needed(session, SIM_DATE)
        _create_purchase_orders_if_needed(session, SIM_DATE + timedelta(days=1))
        count = session.execute(
            select(PurchaseOrder)
            .join(PurchaseOrderLine, PurchaseOrderLine.purchase_order_id == PurchaseOrder.id)
            .where(
                PurchaseOrderLine.product_id == _PRODUCT_ID,
                PurchaseOrder.warehouse_id == _WAREHOUSE_ID,
            )
        ).scalars().all()
        assert len(count) == 1

    def test_does_not_reorder_a_product_with_ample_stock(self, session: Session) -> None:
        _seed_receipt(session, 10_000)
        _create_purchase_orders_if_needed(session, SIM_DATE)
        po = session.execute(
            select(PurchaseOrder)
            .join(PurchaseOrderLine, PurchaseOrderLine.purchase_order_id == PurchaseOrder.id)
            .where(
                PurchaseOrderLine.product_id == _PRODUCT_ID,
                PurchaseOrder.warehouse_id == _WAREHOUSE_ID,
            )
        ).scalar_one_or_none()
        assert po is None

    def test_does_not_create_a_purchase_order_when_a_transfer_is_already_open(
        self, session: Session
    ) -> None:
        _seed_receipt_at(session, _OTHER_WAREHOUSE_ID, 500)
        _create_warehouse_transfers_if_needed(session, SIM_DATE)  # opens a transfer into WH-EAST
        _create_purchase_orders_if_needed(session, SIM_DATE)
        po = session.execute(
            select(PurchaseOrder)
            .join(PurchaseOrderLine, PurchaseOrderLine.purchase_order_id == PurchaseOrder.id)
            .where(
                PurchaseOrderLine.product_id == _PRODUCT_ID,
                PurchaseOrder.warehouse_id == _WAREHOUSE_ID,
            )
        ).scalar_one_or_none()
        assert po is None


class TestCreateWarehouseTransfersIfNeeded:
    def test_creates_a_transfer_from_the_warehouse_with_the_most_surplus(
        self, session: Session
    ) -> None:
        _seed_receipt_at(session, _OTHER_WAREHOUSE_ID, 500)
        _seed_receipt_at(session, _THIRD_WAREHOUSE_ID, 100)
        _create_warehouse_transfers_if_needed(session, SIM_DATE)
        transfer = session.execute(
            select(WarehouseTransfer).where(
                WarehouseTransfer.product_id == _PRODUCT_ID,
                WarehouseTransfer.to_warehouse_id == _WAREHOUSE_ID,
            )
        ).scalar_one()
        assert transfer.from_warehouse_id == _OTHER_WAREHOUSE_ID
        assert transfer.status == TransferStatus.PENDING
        assert transfer.quantity > 0

    def test_writes_a_transfer_out_transaction_at_the_donor_immediately(
        self, session: Session
    ) -> None:
        # WH-WEST is also stocked so only WH-EAST is deficient -- otherwise
        # both WH-EAST and WH-WEST would legitimately draw from WH-CENTRAL,
        # producing two TRANSFER_OUT rows there instead of the one this
        # test targets.
        _seed_receipt_at(session, _OTHER_WAREHOUSE_ID, 500)
        _seed_receipt_at(session, _THIRD_WAREHOUSE_ID, 100)
        before = _current_inventory_position(session, _PRODUCT_ID, _OTHER_WAREHOUSE_ID)
        _create_warehouse_transfers_if_needed(session, SIM_DATE)
        after = _current_inventory_position(session, _PRODUCT_ID, _OTHER_WAREHOUSE_ID)
        txn = session.execute(
            select(InventoryTransaction).where(
                InventoryTransaction.product_id == _PRODUCT_ID,
                InventoryTransaction.warehouse_id == _OTHER_WAREHOUSE_ID,
                InventoryTransaction.transaction_type == InventoryTransactionType.TRANSFER_OUT,
            )
        ).scalar_one()
        assert txn.quantity_delta < 0
        assert before - after == -txn.quantity_delta

    def test_does_not_double_donate_the_same_surplus_within_one_tick(
        self, session: Session
    ) -> None:
        # Bootstrap threshold is 10 (zero demand history); a donor surplus
        # of 15 is not enough to fully satisfy two deficient recipients
        # (WH-EAST and WH-WEST) at 10 each. If the donor's remaining
        # surplus weren't tracked between recipients within the same tick,
        # both transfers would be sized against the same stale figure.
        _seed_receipt_at(session, _OTHER_WAREHOUSE_ID, 25)
        _create_warehouse_transfers_if_needed(session, SIM_DATE)
        transfers = (
            session.execute(
                select(WarehouseTransfer).where(
                    WarehouseTransfer.product_id == _PRODUCT_ID,
                    WarehouseTransfer.from_warehouse_id == _OTHER_WAREHOUSE_ID,
                )
            )
            .scalars()
            .all()
        )
        assert sum(t.quantity for t in transfers) <= 15

    def test_does_not_create_a_transfer_when_a_purchase_order_is_already_open(
        self, session: Session
    ) -> None:
        _seed_receipt_at(session, _OTHER_WAREHOUSE_ID, 500)
        _create_purchase_orders_if_needed(session, SIM_DATE)  # opens a PO for every warehouse
        _create_warehouse_transfers_if_needed(session, SIM_DATE)
        transfer = session.execute(
            select(WarehouseTransfer).where(
                WarehouseTransfer.product_id == _PRODUCT_ID,
                WarehouseTransfer.to_warehouse_id == _WAREHOUSE_ID,
            )
        ).scalar_one_or_none()
        assert transfer is None

    def test_still_creates_pos_when_no_warehouse_has_any_surplus(self, session: Session) -> None:
        # Fresh baseline: every warehouse's position is 0 for this product,
        # so no donor has anything to spare -- transfers must not silently
        # swallow the shortfall; POs still need to fire.
        _create_warehouse_transfers_if_needed(session, SIM_DATE)
        transfer = session.execute(
            select(WarehouseTransfer).where(WarehouseTransfer.product_id == _PRODUCT_ID)
        ).scalar_one_or_none()
        assert transfer is None
        _create_purchase_orders_if_needed(session, SIM_DATE)
        po = session.execute(
            select(PurchaseOrder)
            .join(PurchaseOrderLine, PurchaseOrderLine.purchase_order_id == PurchaseOrder.id)
            .where(
                PurchaseOrderLine.product_id == _PRODUCT_ID,
                PurchaseOrder.warehouse_id == _WAREHOUSE_ID,
            )
        ).scalar_one_or_none()
        assert po is not None

    def test_does_not_open_a_second_transfer_while_one_is_already_open(
        self, session: Session
    ) -> None:
        _seed_receipt_at(session, _OTHER_WAREHOUSE_ID, 500)
        _seed_receipt_at(session, _THIRD_WAREHOUSE_ID, 100)
        _create_warehouse_transfers_if_needed(session, SIM_DATE)
        _create_warehouse_transfers_if_needed(session, SIM_DATE + timedelta(days=1))
        transfers = (
            session.execute(
                select(WarehouseTransfer).where(
                    WarehouseTransfer.product_id == _PRODUCT_ID,
                    WarehouseTransfer.to_warehouse_id == _WAREHOUSE_ID,
                )
            )
            .scalars()
            .all()
        )
        assert len(transfers) == 1


class TestProgressWarehouseTransfers:
    def _insert_transfer(
        self, session: Session, *, status: TransferStatus, transfer_date: date, quantity: int = 20
    ) -> WarehouseTransfer:
        transfer = WarehouseTransfer(
            product_id=_PRODUCT_ID,
            from_warehouse_id=_OTHER_WAREHOUSE_ID,
            to_warehouse_id=_WAREHOUSE_ID,
            quantity=quantity,
            transfer_date=transfer_date,
            status=status,
            source_system=SourceSystem.WMS,
        )
        session.add(transfer)
        session.flush()
        return transfer

    def test_pending_transfer_advances_to_in_transit(self, session: Session) -> None:
        transfer = self._insert_transfer(
            session, status=TransferStatus.PENDING, transfer_date=SIM_DATE
        )
        _progress_warehouse_transfers(session, SIM_DATE)
        session.refresh(transfer)
        assert transfer.status == TransferStatus.IN_TRANSIT

    def test_in_transit_transfer_completes_once_transit_time_has_elapsed(
        self, session: Session
    ) -> None:
        transfer = self._insert_transfer(
            session,
            status=TransferStatus.IN_TRANSIT,
            transfer_date=SIM_DATE - timedelta(days=WAREHOUSE_TRANSFER_TRANSIT_DAYS),
        )
        before = _current_inventory_position(session, _PRODUCT_ID, _WAREHOUSE_ID)
        _progress_warehouse_transfers(session, SIM_DATE)
        session.refresh(transfer)
        after = _current_inventory_position(session, _PRODUCT_ID, _WAREHOUSE_ID)
        assert transfer.status == TransferStatus.COMPLETED
        assert after - before == transfer.quantity

    def test_in_transit_transfer_not_yet_due_stays_in_transit(self, session: Session) -> None:
        transfer = self._insert_transfer(
            session, status=TransferStatus.IN_TRANSIT, transfer_date=SIM_DATE
        )
        _progress_warehouse_transfers(session, SIM_DATE)
        session.refresh(transfer)
        assert transfer.status == TransferStatus.IN_TRANSIT

    def test_completion_writes_a_transfer_in_transaction_at_the_recipient(
        self, session: Session
    ) -> None:
        self._insert_transfer(
            session,
            status=TransferStatus.IN_TRANSIT,
            transfer_date=SIM_DATE - timedelta(days=WAREHOUSE_TRANSFER_TRANSIT_DAYS),
            quantity=30,
        )
        _progress_warehouse_transfers(session, SIM_DATE)
        txn = session.execute(
            select(InventoryTransaction).where(
                InventoryTransaction.product_id == _PRODUCT_ID,
                InventoryTransaction.warehouse_id == _WAREHOUSE_ID,
                InventoryTransaction.transaction_type == InventoryTransactionType.TRANSFER_IN,
            )
        ).scalar_one()
        assert txn.quantity_delta == 30


class TestProgressPurchaseOrders:
    def _insert_po(
        self, session: Session, *, status: PurchaseOrderStatus, expected_delivery_date: date
    ) -> PurchaseOrder:
        po = PurchaseOrder(
            po_number=f"PO-TEST-{uuid.uuid4().hex[:8]}",
            supplier_id=_SUPPLIER_ID,
            warehouse_id=_WAREHOUSE_ID,
            order_date=SIM_DATE - timedelta(days=5),
            expected_delivery_date=expected_delivery_date,
            status=status,
            source_system=SourceSystem.PROCUREMENT,
        )
        session.add(po)
        session.flush()
        session.add(
            PurchaseOrderLine(
                purchase_order_id=po.id,
                product_id=_PRODUCT_ID,
                quantity_ordered=100,
                quantity_received=0,
                unit_cost=1.0,
            )
        )
        session.flush()
        return po

    def test_submitted_po_advances_to_confirmed(self, session: Session) -> None:
        po = self._insert_po(
            session,
            status=PurchaseOrderStatus.SUBMITTED,
            expected_delivery_date=SIM_DATE + timedelta(days=10),
        )
        _progress_purchase_orders(session, SIM_DATE)
        session.refresh(po)
        assert po.status == PurchaseOrderStatus.CONFIRMED

    def test_confirmed_po_past_its_expected_delivery_date_is_received(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Forced to a full receipt (see TestPartialPurchaseOrderReceipt for
        # the seeded-partial path) so this test stays deterministic now
        # that roll_partial_receipt_fraction has real, non-zero odds.
        monkeypatch.setattr(
            "app.services.scheduled_flow.roll_partial_receipt_fraction", lambda *a, **k: None
        )
        po = self._insert_po(
            session,
            status=PurchaseOrderStatus.CONFIRMED,
            expected_delivery_date=SIM_DATE - timedelta(days=1),
        )
        before = _current_inventory_position(session, _PRODUCT_ID, _WAREHOUSE_ID)
        _progress_purchase_orders(session, SIM_DATE)
        session.refresh(po)
        assert po.status == PurchaseOrderStatus.RECEIVED
        after = _current_inventory_position(session, _PRODUCT_ID, _WAREHOUSE_ID)
        assert after - before == 100

    def test_confirmed_po_not_yet_due_stays_confirmed(self, session: Session) -> None:
        po = self._insert_po(
            session,
            status=PurchaseOrderStatus.CONFIRMED,
            expected_delivery_date=SIM_DATE + timedelta(days=5),
        )
        _progress_purchase_orders(session, SIM_DATE)
        session.refresh(po)
        assert po.status == PurchaseOrderStatus.CONFIRMED

    def test_receiving_sets_quantity_received_to_quantity_ordered(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "app.services.scheduled_flow.roll_partial_receipt_fraction", lambda *a, **k: None
        )
        po = self._insert_po(
            session,
            status=PurchaseOrderStatus.CONFIRMED,
            expected_delivery_date=SIM_DATE,
        )
        _progress_purchase_orders(session, SIM_DATE)
        line = session.execute(
            select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == po.id)
        ).scalar_one()
        assert line.quantity_received == line.quantity_ordered == 100


class TestPartialPurchaseOrderReceipt:
    """Unit 30 (MEADOWOPS-DOM-030, PRD 9.2 catalog row 4): a seeded partial
    receipt leaves the PO in PARTIALLY_RECEIVED (not RECEIVED or "missing"),
    with inventory reflecting only what actually arrived, and a later tick
    completes it."""

    def _insert_po(
        self, session: Session, *, status: PurchaseOrderStatus, expected_delivery_date: date
    ) -> PurchaseOrder:
        return TestProgressPurchaseOrders._insert_po(
            self, session, status=status, expected_delivery_date=expected_delivery_date
        )

    def test_a_forced_partial_roll_leaves_the_po_partially_received(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from decimal import Decimal

        monkeypatch.setattr(
            "app.services.scheduled_flow.roll_partial_receipt_fraction",
            lambda *a, **k: Decimal("0.6"),
        )
        po = self._insert_po(
            session,
            status=PurchaseOrderStatus.CONFIRMED,
            expected_delivery_date=SIM_DATE,
        )
        before = _current_inventory_position(session, _PRODUCT_ID, _WAREHOUSE_ID)

        _progress_purchase_orders(session, SIM_DATE)

        session.refresh(po)
        assert po.status == PurchaseOrderStatus.PARTIALLY_RECEIVED
        line = session.execute(
            select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == po.id)
        ).scalar_one()
        assert 0 < line.quantity_received < line.quantity_ordered == 100
        after = _current_inventory_position(session, _PRODUCT_ID, _WAREHOUSE_ID)
        assert after - before == line.quantity_received

    def test_a_later_tick_completes_a_partially_received_po(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from decimal import Decimal

        monkeypatch.setattr(
            "app.services.scheduled_flow.roll_partial_receipt_fraction",
            lambda *a, **k: Decimal("0.6"),
        )
        po = self._insert_po(
            session,
            status=PurchaseOrderStatus.CONFIRMED,
            expected_delivery_date=SIM_DATE,
        )
        _progress_purchase_orders(session, SIM_DATE)
        session.refresh(po)
        assert po.status == PurchaseOrderStatus.PARTIALLY_RECEIVED

        monkeypatch.setattr(
            "app.services.scheduled_flow.roll_partial_receipt_fraction", lambda *a, **k: None
        )
        _progress_purchase_orders(session, SIM_DATE + timedelta(days=1))

        session.refresh(po)
        assert po.status == PurchaseOrderStatus.RECEIVED
        line = session.execute(
            select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == po.id)
        ).scalar_one()
        assert line.quantity_received == line.quantity_ordered == 100

    def test_staying_partially_received_across_two_ticks_does_not_log_a_self_transition(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # code review finding: a PO that rolls partial on two consecutive
        # ticks (PARTIALLY_RECEIVED -> PARTIALLY_RECEIVED) is still real
        # receiving activity, but not a status *transition* -
        # PurchaseOrderLifecycleEvent is documented as recording
        # transitions, so a same-status row here would be audit-trail noise
        # and an inflated event count for a tick that didn't actually
        # change the PO's status.
        from decimal import Decimal

        monkeypatch.setattr(
            "app.services.scheduled_flow.roll_partial_receipt_fraction",
            lambda *a, **k: Decimal("0.3"),
        )
        po = self._insert_po(
            session,
            status=PurchaseOrderStatus.CONFIRMED,
            expected_delivery_date=SIM_DATE,
        )
        first_events = _progress_purchase_orders(session, SIM_DATE)
        session.refresh(po)
        assert po.status == PurchaseOrderStatus.PARTIALLY_RECEIVED
        assert first_events == 1

        second_events = _progress_purchase_orders(session, SIM_DATE + timedelta(days=1))

        session.refresh(po)
        assert po.status == PurchaseOrderStatus.PARTIALLY_RECEIVED
        assert second_events == 0
        logged = session.execute(
            select(PurchaseOrderLifecycleEvent).where(
                PurchaseOrderLifecycleEvent.purchase_order_id == po.id
            )
        ).scalars().all()
        assert len(logged) == 1


class TestSalesOrderAllocationAndShipping:
    def _insert_so(self, session: Session, *, quantity_ordered: int) -> SalesOrder:
        return _insert_so(session, quantity_ordered=quantity_ordered)

    def test_allocates_when_inventory_is_sufficient(self, session: Session) -> None:
        _seed_receipt(session, 50)
        so = self._insert_so(session, quantity_ordered=10)
        _progress_sales_orders_and_shipments(session, SIM_DATE)
        session.refresh(so)
        assert so.status == SalesOrderStatus.ALLOCATED
        assert so.promised_date is not None

    def test_stays_submitted_when_inventory_is_insufficient(self, session: Session) -> None:
        so = self._insert_so(session, quantity_ordered=10)  # no receipt seeded — position 0
        _progress_sales_orders_and_shipments(session, SIM_DATE)
        session.refresh(so)
        assert so.status == SalesOrderStatus.SUBMITTED

    def test_allocated_order_ships_and_creates_a_shipment_with_negative_transaction(
        self, session: Session
    ) -> None:
        _seed_receipt(session, 50)
        so = self._insert_so(session, quantity_ordered=10)
        so.status = SalesOrderStatus.ALLOCATED
        session.flush()
        before = _current_inventory_position(session, _PRODUCT_ID, _WAREHOUSE_ID)
        _progress_sales_orders_and_shipments(session, SIM_DATE)
        session.refresh(so)
        after = _current_inventory_position(session, _PRODUCT_ID, _WAREHOUSE_ID)
        assert so.status == SalesOrderStatus.SHIPPED
        assert before - after == 10
        shipment = session.execute(
            select(Shipment).where(Shipment.sales_order_id == so.id)
        ).scalar_one()
        assert shipment.status == ShipmentStatus.PENDING
        assert shipment.ship_date == SIM_DATE

    def test_partial_inventory_across_two_lines_yields_partially_shipped(
        self, session: Session
    ) -> None:
        _seed_receipt(session, 5)  # enough for one line, not both
        so = self._insert_so(session, quantity_ordered=5)
        session.add(
            SalesOrderLine(
                sales_order_id=so.id,
                product_id="SKU-PRO-001",  # different product, zero stock
                quantity_ordered=5,
                quantity_shipped=0,
                unit_price=1.0,
            )
        )
        so.status = SalesOrderStatus.ALLOCATED
        session.flush()
        _progress_sales_orders_and_shipments(session, SIM_DATE)
        session.refresh(so)
        assert so.status == SalesOrderStatus.PARTIALLY_SHIPPED
        shipment = session.execute(
            select(Shipment).where(Shipment.sales_order_id == so.id)
        ).scalar_one_or_none()
        assert shipment is None  # not fully shipped yet — no shipment row until it is

    def test_pending_shipment_advances_to_in_transit_then_delivered(
        self, session: Session
    ) -> None:
        _seed_receipt(session, 50)
        so = self._insert_so(session, quantity_ordered=10)
        so.status = SalesOrderStatus.ALLOCATED
        session.flush()
        _progress_sales_orders_and_shipments(session, SIM_DATE)  # ships, Shipment -> PENDING
        shipment = session.execute(
            select(Shipment).where(Shipment.sales_order_id == so.id)
        ).scalar_one()

        _progress_sales_orders_and_shipments(session, SIM_DATE + timedelta(days=1))
        session.refresh(shipment)
        assert shipment.status == ShipmentStatus.IN_TRANSIT

        # Carrier variability (Unit 27) can push actual delivery past the
        # promised date -- HIGH variability's spread is 6 days, the widest
        # of the three seeded carriers -- so jump far enough that even the
        # worst-case late roll has resolved, rather than assuming delivery
        # lands exactly on the promise.
        worst_case_delivery = shipment.promised_delivery_date + timedelta(days=6)
        _progress_sales_orders_and_shipments(session, worst_case_delivery)
        session.refresh(shipment)
        assert shipment.status == ShipmentStatus.DELIVERED
        assert shipment.actual_delivery_date is not None
        assert shipment.actual_delivery_date >= shipment.promised_delivery_date
        assert shipment.actual_delivery_date <= worst_case_delivery


class TestShipmentCarrierLateness:
    def test_a_forced_late_roll_actually_changes_the_delivery_outcome(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Forces carrier_actual_transit_days to a wildly late value that
        # could only come from that function, not from promised_delivery_date
        # itself -- proves the service layer genuinely consults it rather
        # than the test window merely being wide enough to pass either way.
        monkeypatch.setattr(
            "app.services.scheduled_flow.carrier_actual_transit_days",
            lambda *args, **kwargs: 999,
        )
        _seed_receipt(session, 50)
        so = _insert_so(session, quantity_ordered=10)
        so.status = SalesOrderStatus.ALLOCATED
        session.flush()
        _progress_sales_orders_and_shipments(session, SIM_DATE)
        shipment = session.execute(
            select(Shipment).where(Shipment.sales_order_id == so.id)
        ).scalar_one()

        _progress_sales_orders_and_shipments(session, SIM_DATE + timedelta(days=1))
        session.refresh(shipment)
        assert shipment.status == ShipmentStatus.IN_TRANSIT

        # The promised date has long passed, but the forced 999-day actual
        # transit hasn't elapsed -- if the service still delivered here, it
        # would prove it isn't consulting carrier_actual_transit_days at all.
        _progress_sales_orders_and_shipments(session, shipment.promised_delivery_date)
        session.refresh(shipment)
        assert shipment.status == ShipmentStatus.IN_TRANSIT

        _progress_sales_orders_and_shipments(session, shipment.ship_date + timedelta(days=999))
        session.refresh(shipment)
        assert shipment.status == ShipmentStatus.DELIVERED
        assert shipment.actual_delivery_date == shipment.ship_date + timedelta(days=999)
        assert shipment.actual_delivery_date > shipment.promised_delivery_date

    def test_the_lateness_roll_is_a_pure_function_of_ship_date_and_shipment_id(
        self, session: Session
    ) -> None:
        # Pins the exact seed convention (_rng(shipment.ship_date,
        # f"carrier_transit:{shipment.id}")) by independently recomputing
        # the expected actual_delivery_date and comparing it to what several
        # intervening progression calls on different dates eventually
        # settle on -- would catch a regression where the seed is (wrongly)
        # keyed off the moving simulation_date instead.
        _seed_receipt(session, 50)
        so = _insert_so(session, quantity_ordered=10)
        so.status = SalesOrderStatus.ALLOCATED
        session.flush()
        _progress_sales_orders_and_shipments(session, SIM_DATE)
        shipment = session.execute(
            select(Shipment).where(Shipment.sales_order_id == so.id)
        ).scalar_one()
        carrier = session.get(Carrier, shipment.carrier_id)

        promised_transit_days = (shipment.promised_delivery_date - shipment.ship_date).days
        expected_rng = random.Random(f"{shipment.ship_date.isoformat()}:carrier_transit:{shipment.id}")
        expected_transit_days = carrier_actual_transit_days(
            promised_transit_days, carrier.variability, float(carrier.reliability_pct), expected_rng
        )
        expected_actual_delivery_date = shipment.ship_date + timedelta(days=expected_transit_days)

        # A few intervening ticks before it's due -- none should perturb
        # the eventually-observed date away from the independently
        # recomputed expectation.
        _progress_sales_orders_and_shipments(session, SIM_DATE + timedelta(days=1))
        for offset in (2, 3):
            _progress_sales_orders_and_shipments(session, SIM_DATE + timedelta(days=offset))
        _progress_sales_orders_and_shipments(
            session, expected_actual_delivery_date + timedelta(days=1)
        )
        session.refresh(shipment)
        assert shipment.status == ShipmentStatus.DELIVERED
        assert shipment.actual_delivery_date == expected_actual_delivery_date


class TestCreateSalesOrdersIfNeeded:
    def test_is_deterministic_across_separate_sessions_for_the_same_date(self) -> None:
        engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
        results = []
        for _ in range(2):
            with Session(engine) as s:
                seed_master_data(s)
                s.commit()
                _create_sales_orders_if_needed(s, SIM_DATE)
                rows = s.execute(
                    select(SalesOrder.customer_id, SalesOrderLine.product_id, SalesOrderLine.quantity_ordered)
                    .join(SalesOrderLine, SalesOrderLine.sales_order_id == SalesOrder.id)
                    .where(SalesOrder.order_date == SIM_DATE)
                    .order_by(SalesOrder.customer_id, SalesOrderLine.product_id)
                ).all()
                results.append(rows)
                s.rollback()
        engine.dispose()
        assert results[0] == results[1]
        assert len(results[0]) > 0  # the fixed seed does produce at least one order

    def test_creates_at_least_one_lifecycle_event_per_order(self, session: Session) -> None:
        created = _create_sales_orders_if_needed(session, SIM_DATE)
        events = session.execute(
            select(SalesOrderLifecycleEvent).where(
                SalesOrderLifecycleEvent.simulation_date == SIM_DATE
            )
        ).scalars().all()
        assert len(events) == created
        assert all(e.from_status is None for e in events)


class TestSnapshotInventoryPositions:
    def test_writes_on_hand_quantity_derived_from_the_transaction_ledger(
        self, session: Session
    ) -> None:
        _seed_receipt(session, 50)
        _snapshot_inventory_positions(session, SIM_DATE)
        snap = session.execute(
            select(InventorySnapshot).where(
                InventorySnapshot.snapshot_date == SIM_DATE,
                InventorySnapshot.product_id == _PRODUCT_ID,
                InventorySnapshot.warehouse_id == _WAREHOUSE_ID,
            )
        ).scalar_one()
        assert snap.quantity_on_hand == 50
        assert snap.quantity_allocated == 0

    def test_writes_allocated_quantity_from_open_sales_order_lines(self, session: Session) -> None:
        _seed_receipt(session, 50)
        so = SalesOrder(
            so_number=f"SO-TEST-{uuid.uuid4().hex[:8]}",
            customer_id=_CUSTOMER_ID,
            warehouse_id=_WAREHOUSE_ID,
            order_date=SIM_DATE,
            requested_date=SIM_DATE + timedelta(days=2),
            status=SalesOrderStatus.ALLOCATED,
            source_system=SourceSystem.ERP,
        )
        session.add(so)
        session.flush()
        session.add(
            SalesOrderLine(
                sales_order_id=so.id,
                product_id=_PRODUCT_ID,
                quantity_ordered=15,
                quantity_shipped=0,
                unit_price=1.0,
            )
        )
        session.flush()

        _snapshot_inventory_positions(session, SIM_DATE)
        snap = session.execute(
            select(InventorySnapshot).where(
                InventorySnapshot.snapshot_date == SIM_DATE,
                InventorySnapshot.product_id == _PRODUCT_ID,
                InventorySnapshot.warehouse_id == _WAREHOUSE_ID,
            )
        ).scalar_one()
        assert snap.quantity_allocated == 15

    def test_rerunning_the_same_day_replaces_rather_than_duplicates(
        self, session: Session
    ) -> None:
        _seed_receipt(session, 50)
        _snapshot_inventory_positions(session, SIM_DATE)
        _seed_receipt(session, 25)  # position now 75
        _snapshot_inventory_positions(session, SIM_DATE)
        rows = session.execute(
            select(InventorySnapshot).where(
                InventorySnapshot.snapshot_date == SIM_DATE,
                InventorySnapshot.product_id == _PRODUCT_ID,
                InventorySnapshot.warehouse_id == _WAREHOUSE_ID,
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].quantity_on_hand == 75

    def test_run_scheduled_tick_writes_snapshots_for_active_products_and_warehouses(
        self, session: Session
    ) -> None:
        run_scheduled_tick(session, SIM_DATE)
        count = session.execute(
            select(InventorySnapshot).where(InventorySnapshot.snapshot_date == SIM_DATE)
        ).scalars().all()
        assert len(count) > 0  # 20 products x 3 warehouses in the seeded baseline


class TestRunScheduledTick:
    def test_writes_a_success_tick_with_the_correct_event_count(self, session: Session) -> None:
        tick = run_scheduled_tick(session, SIM_DATE)
        assert tick.status == ScheduledTickStatus.SUCCESS
        assert tick.simulation_date == SIM_DATE
        stored = session.execute(
            select(ScheduledTick).where(ScheduledTick.id == tick.id)
        ).scalar_one()
        assert stored.events_generated == tick.events_generated
        assert stored.events_generated > 0  # baseline data guarantees at least the PO bootstrap

    def test_writes_a_failed_tick_and_reraises_on_error(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*args: object, **kwargs: object) -> int:
            raise RuntimeError("simulated failure")

        monkeypatch.setattr(
            "app.services.scheduled_flow._progress_purchase_orders", _boom
        )
        with pytest.raises(RuntimeError, match="simulated failure"):
            run_scheduled_tick(session, SIM_DATE)
        tick = session.execute(
            select(ScheduledTick).where(ScheduledTick.simulation_date == SIM_DATE)
        ).scalar_one()
        assert tick.status == ScheduledTickStatus.FAILED
        assert tick.events_generated == 0

    def test_a_real_db_constraint_violation_still_writes_the_failed_tick(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # security review finding: a *DB-level* exception (unlike a plain
        # Python exception) leaves the session in "pending rollback" state,
        # which the FAILED-tick write must recover from via rollback()
        # first — otherwise that recovery write itself raises
        # PendingRollbackError and the audit row is lost. Reproduced here
        # with a genuine FK violation, not a mocked exception, since a
        # mocked raise doesn't actually dirty the session's transactional
        # state the way a real failed flush does.
        def _real_fk_violation(*args: object, **kwargs: object) -> int:
            session.execute(
                text(
                    "INSERT INTO live.purchase_order_lifecycle_event "
                    "(purchase_order_id, to_status, simulation_date) "
                    "VALUES (gen_random_uuid(), 'submitted', :d)"
                ),
                {"d": SIM_DATE},
            )
            session.flush()
            return 0

        monkeypatch.setattr(
            "app.services.scheduled_flow._progress_purchase_orders", _real_fk_violation
        )
        with pytest.raises(IntegrityError):
            run_scheduled_tick(session, SIM_DATE)
        tick = session.execute(
            select(ScheduledTick).where(ScheduledTick.simulation_date == SIM_DATE)
        ).scalar_one()
        assert tick.status == ScheduledTickStatus.FAILED
