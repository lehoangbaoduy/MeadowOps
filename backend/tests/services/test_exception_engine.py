"""Unit 15 (MEADOWOPS-DOM-008): exception engine, transactional layer.
Runs against real seeded baseline data (Unit 5) plus the real seeded
exception-rule thresholds (Unit 10), inside an uncommitted transaction per
test — same non-autocommit discipline as every other DB test in this suite.
"""

import os
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.enums import (
    PurchaseOrderStatus,
    SalesOrderStatus,
    ShipmentStatus,
    SourceSystem,
)
from app.db.exception_flags import ExceptionFlag
from app.db.exception_rules import ExceptionRuleThreshold
from app.db.facts import (
    InventorySnapshot,
    PurchaseOrder,
    PurchaseOrderLine,
    SalesOrder,
    SalesOrderLine,
    Shipment,
)
from app.services.baseline_data import seed_master_data
from app.domain.reporting_sync import KNOWN_CONFLICT_QTY_OFFSET
from app.services.exception_engine import (
    AT_RISK_PO_CATEGORY,
    DUPLICATE_PURCHASE_ORDER_CATEGORY,
    LATE_SHIPMENT_CATEGORY,
    LOW_STOCK_CATEGORY,
    REPORTING_CONFLICT_CATEGORY,
    REPORTING_LAG_STALE_CATEGORY,
    evaluate_exceptions,
)
from app.services.exception_rule_defaults import seed_exception_rule_thresholds
from app.services.reporting_sync import sync_reporting_layer

SIM_DATE = date(2026, 3, 2)
_PRODUCT_ID = "SKU-COR-001"
_WAREHOUSE_ID = "WH-EAST"
_SUPPLIER_ID = "S-001"
_CUSTOMER_ID = "CUST-EAST-01"


@pytest.fixture
def session():
    engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
    with Session(engine) as session:
        seed_master_data(session)
        seed_exception_rule_thresholds(session)
        session.commit()
        yield session
        session.rollback()
    engine.dispose()


def _purchase_order(
    session: Session,
    *,
    expected_delivery_date: date,
    status: PurchaseOrderStatus,
    product_id: str = _PRODUCT_ID,
) -> PurchaseOrder:
    po = PurchaseOrder(
        po_number=f"PO-TEST-{uuid.uuid4().hex[:8]}",
        supplier_id=_SUPPLIER_ID,
        warehouse_id=_WAREHOUSE_ID,
        order_date=expected_delivery_date - timedelta(days=7),
        expected_delivery_date=expected_delivery_date,
        status=status,
        source_system=SourceSystem.ERP,
    )
    session.add(po)
    session.flush()
    # Matches production usage (app.services.scheduled_flow._create_
    # purchase_orders_if_needed always creates exactly one line per PO) -
    # code review finding: the duplicate-PO grouping key includes
    # product_id, so a lineless test PO can no longer exercise that path.
    session.add(
        PurchaseOrderLine(
            purchase_order_id=po.id,
            product_id=product_id,
            quantity_ordered=10,
            quantity_received=0,
            unit_cost=1,
        )
    )
    session.flush()
    return po


def _shipment(
    session: Session,
    *,
    promised_delivery_date: date,
    actual_delivery_date: date | None,
    status: ShipmentStatus,
) -> Shipment:
    so = SalesOrder(
        so_number=f"SO-TEST-{uuid.uuid4().hex[:8]}",
        customer_id=_CUSTOMER_ID,
        warehouse_id=_WAREHOUSE_ID,
        order_date=promised_delivery_date - timedelta(days=5),
        requested_date=promised_delivery_date,
        status=SalesOrderStatus.SHIPPED,
        source_system=SourceSystem.ERP,
    )
    session.add(so)
    session.flush()
    session.add(
        SalesOrderLine(
            sales_order_id=so.id,
            product_id=_PRODUCT_ID,
            quantity_ordered=5,
            quantity_shipped=5,
            unit_price=1.0,
        )
    )
    shipment = Shipment(
        sales_order_id=so.id,
        carrier_id="C-001",
        warehouse_id=_WAREHOUSE_ID,
        ship_date=promised_delivery_date - timedelta(days=2),
        promised_delivery_date=promised_delivery_date,
        actual_delivery_date=actual_delivery_date,
        status=status,
        source_system=SourceSystem.WMS,
    )
    session.add(shipment)
    session.flush()
    return shipment


def _open_flags(session: Session, category: str) -> list[ExceptionFlag]:
    return list(
        session.execute(
            select(ExceptionFlag).where(
                ExceptionFlag.category == category, ExceptionFlag.resolved_at.is_(None)
            )
        ).scalars()
    )


class TestAtRiskPurchaseOrderFlags:
    def test_opens_a_flag_for_a_past_due_open_purchase_order(self, session: Session) -> None:
        po = _purchase_order(
            session,
            expected_delivery_date=SIM_DATE - timedelta(days=1),
            status=PurchaseOrderStatus.SUBMITTED,
        )
        result = evaluate_exceptions(session, SIM_DATE)
        assert result.opened >= 1
        flags = _open_flags(session, AT_RISK_PO_CATEGORY)
        assert any(f.purchase_order_id == po.id for f in flags)

    def test_does_not_flag_a_purchase_order_within_grace(self, session: Session) -> None:
        _purchase_order(
            session, expected_delivery_date=SIM_DATE, status=PurchaseOrderStatus.SUBMITTED
        )
        evaluate_exceptions(session, SIM_DATE)
        flags = _open_flags(session, AT_RISK_PO_CATEGORY)
        assert flags == []

    def test_does_not_flag_a_received_purchase_order(self, session: Session) -> None:
        _purchase_order(
            session,
            expected_delivery_date=SIM_DATE - timedelta(days=10),
            status=PurchaseOrderStatus.RECEIVED,
        )
        evaluate_exceptions(session, SIM_DATE)
        flags = _open_flags(session, AT_RISK_PO_CATEGORY)
        assert flags == []

    def test_re_evaluating_after_the_po_is_received_auto_resolves_the_flag(
        self, session: Session
    ) -> None:
        po = _purchase_order(
            session,
            expected_delivery_date=SIM_DATE - timedelta(days=1),
            status=PurchaseOrderStatus.SUBMITTED,
        )
        evaluate_exceptions(session, SIM_DATE)
        assert len(_open_flags(session, AT_RISK_PO_CATEGORY)) == 1

        po.status = PurchaseOrderStatus.RECEIVED
        session.flush()
        result = evaluate_exceptions(session, SIM_DATE + timedelta(days=1))
        assert result.resolved >= 1
        assert _open_flags(session, AT_RISK_PO_CATEGORY) == []

    def test_re_evaluating_while_still_at_risk_does_not_duplicate_the_flag(
        self, session: Session
    ) -> None:
        _purchase_order(
            session,
            expected_delivery_date=SIM_DATE - timedelta(days=1),
            status=PurchaseOrderStatus.SUBMITTED,
        )
        evaluate_exceptions(session, SIM_DATE)
        evaluate_exceptions(session, SIM_DATE + timedelta(days=1))
        assert len(_open_flags(session, AT_RISK_PO_CATEGORY)) == 1

    def test_threshold_value_and_first_detected_date_are_frozen_at_detection(
        self, session: Session
    ) -> None:
        # Security review (MEDIUM): an already-open flag's threshold_value
        # and first_detected_simulation_date must not be rewritten by a
        # later re-sync, even though the Analyst-adjustable threshold
        # (S1-FR-10) or the current simulation_date changes — otherwise
        # the flag's own audit trail of "what triggered this, and when"
        # would silently drift.
        _purchase_order(
            session,
            expected_delivery_date=SIM_DATE - timedelta(days=1),
            status=PurchaseOrderStatus.SUBMITTED,
        )
        evaluate_exceptions(session, SIM_DATE)
        flag = _open_flags(session, AT_RISK_PO_CATEGORY)[0]
        assert flag.threshold_value == 0
        assert flag.first_detected_simulation_date == SIM_DATE
        assert flag.simulation_date == SIM_DATE

        session.execute(
            update(ExceptionRuleThreshold)
            .where(ExceptionRuleThreshold.id == AT_RISK_PO_CATEGORY)
            .values(threshold_value=5)
        )
        session.flush()

        later_date = SIM_DATE + timedelta(days=10)
        evaluate_exceptions(session, later_date)

        flags = _open_flags(session, AT_RISK_PO_CATEGORY)
        assert len(flags) == 1
        refreshed = flags[0]
        assert refreshed.id == flag.id
        assert refreshed.threshold_value == 0  # frozen — not the new 5
        assert refreshed.first_detected_simulation_date == SIM_DATE  # frozen
        assert refreshed.simulation_date == later_date  # last-observed does update

    def test_advisory_lock_is_held_for_the_duration_of_the_call(self, session: Session) -> None:
        # Security review (MEDIUM): evaluate_exceptions must hold a
        # Postgres advisory transaction lock so overlapping calls
        # serialize instead of racing _sync_flags's read-then-decide-then
        # -write reconciliation. pg_advisory_xact_lock auto-releases at
        # transaction end, so checking pg_locks from a second connection
        # while this session's transaction is still open (no commit yet)
        # confirms the lock is genuinely being taken, not just present in
        # the source.
        evaluate_exceptions(session, SIM_DATE)
        other_engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
        with other_engine.connect() as other_conn:
            (count,) = other_conn.execute(
                text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'")
            ).one()
        other_engine.dispose()
        assert count >= 1


class TestDuplicatePurchaseOrderFlags:
    """Unit 30 (MEADOWOPS-DOM-030, PRD 9.2 catalog row 2 / SR-3): injected
    duplicate records are detected and flagged, not silently deduplicated
    or accepted."""

    def test_flags_the_later_of_two_matching_open_pos(self, session: Session) -> None:
        first = _purchase_order(
            session,
            expected_delivery_date=SIM_DATE + timedelta(days=5),
            status=PurchaseOrderStatus.SUBMITTED,
        )
        second = _purchase_order(
            session,
            expected_delivery_date=SIM_DATE + timedelta(days=5),
            status=PurchaseOrderStatus.SUBMITTED,
        )
        # _purchase_order derives order_date from expected_delivery_date
        # alone, so both share the same value by default - bump the second
        # one forward so the group's "earliest = original" tie-break is
        # deterministic rather than falling back to comparing random UUIDs.
        second.order_date = first.order_date + timedelta(days=1)
        session.flush()

        result = evaluate_exceptions(session, SIM_DATE)
        assert result.opened >= 1
        flags = _open_flags(session, DUPLICATE_PURCHASE_ORDER_CATEGORY)
        flagged_ids = {f.purchase_order_id for f in flags}
        assert second.id in flagged_ids
        assert first.id not in flagged_ids

    def test_does_not_flag_a_single_po_with_no_match(self, session: Session) -> None:
        _purchase_order(
            session,
            expected_delivery_date=SIM_DATE + timedelta(days=5),
            status=PurchaseOrderStatus.SUBMITTED,
        )
        evaluate_exceptions(session, SIM_DATE)
        assert _open_flags(session, DUPLICATE_PURCHASE_ORDER_CATEGORY) == []

    def test_does_not_flag_two_pos_on_different_delivery_dates(self, session: Session) -> None:
        _purchase_order(
            session,
            expected_delivery_date=SIM_DATE + timedelta(days=5),
            status=PurchaseOrderStatus.SUBMITTED,
        )
        _purchase_order(
            session,
            expected_delivery_date=SIM_DATE + timedelta(days=6),
            status=PurchaseOrderStatus.SUBMITTED,
        )
        evaluate_exceptions(session, SIM_DATE)
        assert _open_flags(session, DUPLICATE_PURCHASE_ORDER_CATEGORY) == []

    def test_does_not_flag_two_pos_for_different_products_on_the_same_date(
        self, session: Session
    ) -> None:
        # Code review finding: the grouping key must include product_id -
        # app.services.scheduled_flow.assign_supplier is deterministic per
        # ProductCategory, so two different products in the same category
        # reordering at the same warehouse can land on the identical
        # expected_delivery_date by chance. Without product_id in the key,
        # this would be a false-positive duplicate flag on two genuinely
        # independent orders.
        first = _purchase_order(
            session,
            expected_delivery_date=SIM_DATE + timedelta(days=5),
            status=PurchaseOrderStatus.SUBMITTED,
            product_id=_PRODUCT_ID,
        )
        second = _purchase_order(
            session,
            expected_delivery_date=SIM_DATE + timedelta(days=5),
            status=PurchaseOrderStatus.SUBMITTED,
            product_id="SKU-COR-002",
        )
        evaluate_exceptions(session, SIM_DATE)
        flags = _open_flags(session, DUPLICATE_PURCHASE_ORDER_CATEGORY)
        flagged_ids = {f.purchase_order_id for f in flags}
        assert first.id not in flagged_ids
        assert second.id not in flagged_ids

    def test_re_evaluating_after_the_duplicate_is_cancelled_auto_resolves_the_flag(
        self, session: Session
    ) -> None:
        _purchase_order(
            session,
            expected_delivery_date=SIM_DATE + timedelta(days=5),
            status=PurchaseOrderStatus.SUBMITTED,
        )
        second = _purchase_order(
            session,
            expected_delivery_date=SIM_DATE + timedelta(days=5),
            status=PurchaseOrderStatus.SUBMITTED,
        )
        evaluate_exceptions(session, SIM_DATE)
        assert len(_open_flags(session, DUPLICATE_PURCHASE_ORDER_CATEGORY)) == 1

        second.status = PurchaseOrderStatus.CANCELLED
        session.flush()
        result = evaluate_exceptions(session, SIM_DATE)
        assert result.resolved >= 1
        assert _open_flags(session, DUPLICATE_PURCHASE_ORDER_CATEGORY) == []


class TestLateShipmentFlags:
    def test_opens_a_flag_for_an_undelivered_shipment_past_promised_date(
        self, session: Session
    ) -> None:
        shipment = _shipment(
            session,
            promised_delivery_date=SIM_DATE - timedelta(days=1),
            actual_delivery_date=None,
            status=ShipmentStatus.IN_TRANSIT,
        )
        evaluate_exceptions(session, SIM_DATE)
        flags = _open_flags(session, LATE_SHIPMENT_CATEGORY)
        assert any(f.shipment_id == shipment.id for f in flags)

    def test_opens_a_flag_for_a_shipment_delivered_late(self, session: Session) -> None:
        shipment = _shipment(
            session,
            promised_delivery_date=SIM_DATE - timedelta(days=5),
            actual_delivery_date=SIM_DATE - timedelta(days=1),
            status=ShipmentStatus.DELIVERED,
        )
        evaluate_exceptions(session, SIM_DATE)
        flags = _open_flags(session, LATE_SHIPMENT_CATEGORY)
        assert any(f.shipment_id == shipment.id for f in flags)

    def test_does_not_flag_a_shipment_delivered_on_time(self, session: Session) -> None:
        _shipment(
            session,
            promised_delivery_date=SIM_DATE - timedelta(days=5),
            actual_delivery_date=SIM_DATE - timedelta(days=5),
            status=ShipmentStatus.DELIVERED,
        )
        evaluate_exceptions(session, SIM_DATE)
        assert _open_flags(session, LATE_SHIPMENT_CATEGORY) == []


class TestLowStockFlags:
    def test_no_flag_from_a_snapshot_with_undefined_days_of_supply(self, session: Session) -> None:
        # Zero shipment activity -> days_of_supply.sql's avg_daily_usage CTE
        # has no matching rows -> NULLIF denominator is NULL -> days_of_supply
        # is NULL, which evaluate_low_stock treats as "undefined, don't
        # flag" (Unit 10's own documented degradation). The genuine
        # below-threshold case is exercised at the domain-logic level
        # (test_exception_engine.py, evaluate_low_stock directly); here we
        # confirm the engine wires that correctly end-to-end and produces
        # no false low-stock flags from a snapshot with no usage history.
        session.add(
            InventorySnapshot(
                snapshot_date=SIM_DATE,
                product_id=_PRODUCT_ID,
                warehouse_id=_WAREHOUSE_ID,
                quantity_on_hand=0,
                quantity_allocated=0,
                source_system=SourceSystem.WMS,
            )
        )
        session.flush()
        evaluate_exceptions(session, SIM_DATE)
        flags = _open_flags(session, LOW_STOCK_CATEGORY)
        assert flags == []

    def test_inconclusive_evaluation_leaves_an_existing_open_flag_untouched(
        self, session: Session
    ) -> None:
        # Security review (HIGH): a flag opened on an earlier day (real
        # below-threshold usage existed then) must NOT be auto-resolved
        # just because shipment activity has since fallen out of the
        # trailing 30-day window and days_of_supply.sql now returns NULL
        # for this key — an undefined ratio is "can't measure it this
        # tick," not "condition cleared."
        session.add(
            InventorySnapshot(
                snapshot_date=SIM_DATE,
                product_id=_PRODUCT_ID,
                warehouse_id=_WAREHOUSE_ID,
                quantity_on_hand=1,
                quantity_allocated=0,
                source_system=SourceSystem.WMS,
            )
        )
        session.add(
            ExceptionFlag(
                category=LOW_STOCK_CATEGORY,
                product_id=_PRODUCT_ID,
                warehouse_id=_WAREHOUSE_ID,
                simulation_date=SIM_DATE - timedelta(days=5),
                first_detected_simulation_date=SIM_DATE - timedelta(days=5),
                measured_value=2,
                threshold_value=14,
            )
        )
        session.flush()

        result = evaluate_exceptions(session, SIM_DATE)

        assert result.resolved == 0
        flags = _open_flags(session, LOW_STOCK_CATEGORY)
        assert any(
            f.product_id == _PRODUCT_ID and f.warehouse_id == _WAREHOUSE_ID for f in flags
        )

    def test_db_rejects_a_second_open_flag_for_the_same_product_and_warehouse(
        self, session: Session
    ) -> None:
        # The real correctness question the partial unique index exists to
        # answer: for this category, purchase_order_id and shipment_id are
        # BOTH always NULL, and Postgres treats NULL as distinct from NULL
        # in a plain unique index — so a naive index would let this insert
        # succeed twice. ux_exception_flag_open_entity uses COALESCE(...,
        # '') specifically so this raises instead.
        kwargs = dict(
            category=LOW_STOCK_CATEGORY,
            product_id=_PRODUCT_ID,
            warehouse_id=_WAREHOUSE_ID,
            simulation_date=SIM_DATE,
            first_detected_simulation_date=SIM_DATE,
            threshold_value=14,
        )
        session.add(ExceptionFlag(**kwargs))
        session.flush()
        session.add(ExceptionFlag(**kwargs))
        with pytest.raises(IntegrityError):
            session.flush()


class TestEvaluateExceptionsIsSafeToRerun:
    def test_running_twice_with_no_data_yields_no_flags_and_no_error(
        self, session: Session
    ) -> None:
        result = evaluate_exceptions(session, SIM_DATE)
        assert result.opened == 0
        result_again = evaluate_exceptions(session, SIM_DATE)
        assert result_again.opened == 0


class TestReportingLagStaleFlags:
    def test_never_synced_does_not_open_a_flag(self, session: Session) -> None:
        result = evaluate_exceptions(session, SIM_DATE)
        assert result.opened == 0
        flag = session.execute(
            select(ExceptionFlag).where(ExceptionFlag.category == REPORTING_LAG_STALE_CATEGORY)
        ).scalar_one_or_none()
        assert flag is None

    def test_opens_a_flag_once_the_lag_exceeds_the_configured_window(
        self, session: Session
    ) -> None:
        session.add(
            InventorySnapshot(
                snapshot_date=SIM_DATE,
                product_id=_PRODUCT_ID,
                warehouse_id=_WAREHOUSE_ID,
                quantity_on_hand=100,
                quantity_allocated=0,
                source_system=SourceSystem.WMS,
            )
        )
        session.flush()
        sync_reporting_layer(session, SIM_DATE + timedelta(days=2), lag_days=2)

        # Simulated scheduler downtime (PRD 9.2): sync_reporting_layer is
        # simply never called again while simulation_date keeps moving —
        # evaluate_exceptions alone, called on a much later date, must
        # still detect and surface the staleness.
        much_later = SIM_DATE + timedelta(days=30)
        result = evaluate_exceptions(session, much_later)
        # >=1, not ==1: the same seeded product also becomes the SR-4
        # conflict entity (it's the only one seeded), so a
        # reporting_conflict_qty_variance flag opens alongside it in this
        # scenario — that's TestReportingConflictFlags' own concern, not
        # this test's.
        assert result.opened >= 1
        flag = session.execute(
            select(ExceptionFlag).where(
                ExceptionFlag.category == REPORTING_LAG_STALE_CATEGORY,
                ExceptionFlag.resolved_at.is_(None),
            )
        ).scalar_one()
        assert flag.product_id is None
        assert flag.warehouse_id is None

    def test_resolves_once_sync_catches_back_up(self, session: Session) -> None:
        session.add(
            InventorySnapshot(
                snapshot_date=SIM_DATE,
                product_id=_PRODUCT_ID,
                warehouse_id=_WAREHOUSE_ID,
                quantity_on_hand=100,
                quantity_allocated=0,
                source_system=SourceSystem.WMS,
            )
        )
        session.flush()
        sync_reporting_layer(session, SIM_DATE + timedelta(days=2), lag_days=2)
        evaluate_exceptions(session, SIM_DATE + timedelta(days=30))  # opens the flag

        # Sync resumes and fully catches up.
        for offset in range(1, 30):
            session.add(
                InventorySnapshot(
                    snapshot_date=SIM_DATE + timedelta(days=offset),
                    product_id=_PRODUCT_ID,
                    warehouse_id=_WAREHOUSE_ID,
                    quantity_on_hand=100,
                    quantity_allocated=0,
                    source_system=SourceSystem.WMS,
                )
            )
        session.flush()
        sync_reporting_layer(session, SIM_DATE + timedelta(days=32), lag_days=2)

        result = evaluate_exceptions(session, SIM_DATE + timedelta(days=32))
        assert result.resolved == 1


class TestReportingConflictFlags:
    def test_no_sync_yet_does_not_open_a_flag(self, session: Session) -> None:
        result = evaluate_exceptions(session, SIM_DATE)
        assert result.opened == 0
        flag = session.execute(
            select(ExceptionFlag).where(ExceptionFlag.category == REPORTING_CONFLICT_CATEGORY)
        ).scalar_one_or_none()
        assert flag is None

    def test_opens_a_flag_for_the_seeded_conflict_entity_with_the_known_variance(
        self, session: Session
    ) -> None:
        session.add(
            InventorySnapshot(
                snapshot_date=SIM_DATE,
                product_id=_PRODUCT_ID,
                warehouse_id=_WAREHOUSE_ID,
                quantity_on_hand=100,
                quantity_allocated=0,
                source_system=SourceSystem.WMS,
            )
        )
        session.flush()
        sync_reporting_layer(session, SIM_DATE + timedelta(days=2), lag_days=2)

        result = evaluate_exceptions(session, SIM_DATE + timedelta(days=2))
        assert result.opened >= 1
        flag = session.execute(
            select(ExceptionFlag).where(
                ExceptionFlag.category == REPORTING_CONFLICT_CATEGORY,
                ExceptionFlag.resolved_at.is_(None),
            )
        ).scalar_one()
        assert flag.product_id == _PRODUCT_ID
        assert flag.warehouse_id == _WAREHOUSE_ID
        assert flag.measured_value == KNOWN_CONFLICT_QTY_OFFSET

    def test_stays_open_across_further_ticks_not_resolvable_by_timing(
        self, session: Session
    ) -> None:
        session.add(
            InventorySnapshot(
                snapshot_date=SIM_DATE,
                product_id=_PRODUCT_ID,
                warehouse_id=_WAREHOUSE_ID,
                quantity_on_hand=100,
                quantity_allocated=0,
                source_system=SourceSystem.WMS,
            )
        )
        session.flush()
        sync_reporting_layer(session, SIM_DATE + timedelta(days=2), lag_days=2)
        evaluate_exceptions(session, SIM_DATE + timedelta(days=2))

        for offset in range(1, 10):
            session.add(
                InventorySnapshot(
                    snapshot_date=SIM_DATE + timedelta(days=offset),
                    product_id=_PRODUCT_ID,
                    warehouse_id=_WAREHOUSE_ID,
                    quantity_on_hand=100 + offset,
                    quantity_allocated=0,
                    source_system=SourceSystem.WMS,
                )
            )
            session.flush()
            sync_reporting_layer(session, SIM_DATE + timedelta(days=offset + 2), lag_days=2)
            evaluate_exceptions(session, SIM_DATE + timedelta(days=offset + 2))

        flag = session.execute(
            select(ExceptionFlag).where(
                ExceptionFlag.category == REPORTING_CONFLICT_CATEGORY,
                ExceptionFlag.resolved_at.is_(None),
            )
        ).scalar_one()
        assert flag.measured_value == KNOWN_CONFLICT_QTY_OFFSET
