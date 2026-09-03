"""Unit 16 (MEADOWOPS-API-003): dashboard API + drill-down endpoints for the
five S1-FR-5 views. Fixture data uses ZZTEST- ids (DD-9/DD-10 discipline,
same convention as tests/api/test_master_data.py) and is fully isolated
from the seeded baseline catalog and from every other unit's data.

Unlike test_master_data.py's CRUD rows, this unit is read-only, so the
fixture rows must be COMMITTED (not just flushed) to be visible to the
TestClient's own request-scoped session, which opens its own connection —
Postgres's READ COMMITTED isolation means an uncommitted row on one
connection is invisible to another. The autouse cleanup fixture deletes
every row it created, in dependency order, so the shared dev database is
left exactly as it was found (other units, e.g. tests/services/
test_kpi_engine.py, assert "no data yields all-None" against these same
tables and would break if this fixture leaked rows).

Reconciliation, not just shape: for every summary/aggregate endpoint, at
least one test recomputes the expected figure independently — either from
the exact fixture rows created here, or from a second endpoint's own
response — and asserts the two agree, per this unit's own spec (id 207):
"a drill-down response must reconcile to the number above it."
"""

import os
import uuid
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.dimensions import Carrier, Customer, Product, Supplier, Warehouse
from app.db.enums import (
    InventoryTransactionType,
    ProductCategory,
    PurchaseOrderStatus,
    SalesOrderStatus,
    ServicePriority,
    ShipmentStatus,
    SourceSystem,
    Variability,
    CostTier,
)
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
from app.main import create_app
from app.services.exception_engine import (
    AT_RISK_PO_CATEGORY,
    LATE_SHIPMENT_CATEGORY,
    LOW_STOCK_CATEGORY,
)
from app.services.exception_rule_defaults import seed_exception_rule_thresholds
from app.services.kpi_engine import compute_and_snapshot_kpis
from tests.support.auth import TEST_SESSION_SECRET, make_token

_TOKEN = make_token("admin")
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}
_ANALYST_AUTH = {"Authorization": f"Bearer {make_token('analyst')}"}

_WAREHOUSE_ID = "ZZTEST-WH-DASH-01"
_PRODUCT_ID = "ZZTEST-SKU-DASH-01"
_SUPPLIER_ID = "ZZTEST-S-DASH-01"
_CUSTOMER_ID = "ZZTEST-CUST-DASH-01"
_CARRIER_ID = "ZZTEST-C-DASH-01"

# Far enough in the future that compute_and_snapshot_kpis's out-of-order
# guard (KpiComputationOutOfOrderError, Unit 14) can never see this as
# earlier than a real tick's simulation_date — the scheduler is disabled by
# default (settings.scheduler_enabled=False) so kpi_snapshot is empty in
# practice, but this makes the test robust even if that ever changes.
SIM_DATE = date(2099, 6, 15)


@dataclass
class _Scenario:
    at_risk_po_id: uuid.UUID
    closed_po_id: uuid.UUID
    on_time_so_id: uuid.UUID
    late_so_id: uuid.UUID
    on_time_shipment_id: uuid.UUID
    late_shipment_id: uuid.UUID
    at_risk_flag_id: uuid.UUID
    late_flag_id: uuid.UUID
    low_stock_flag_id: uuid.UUID
    inventory_transaction_ids: list[uuid.UUID] = field(default_factory=list)


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(create_app(settings=Settings(session_secret_key=TEST_SESSION_SECRET))) as c:
        yield c


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def scenario(db_session: Session) -> Generator[_Scenario, None, None]:
    session = db_session
    seed_exception_rule_thresholds(session)

    # Warehouse flushed on its own, ahead of Customer — Customer.warehouse_id
    # is a FK to it, and this fixture would rather be explicit about insert
    # order than lean on the unit-of-work's cross-table dependency sort.
    session.add(
        Warehouse(id=_WAREHOUSE_ID, name="ZZTEST Dash WH", region="Test Region", capacity_pallet_positions=1000)
    )
    session.flush()
    session.add(
        Product(
            id=_PRODUCT_ID,
            sku=_PRODUCT_ID,
            name="ZZTEST Dash Product",
            category=ProductCategory.CORRUGATED_PACKAGING,
            unit_cost=Decimal("2.50"),
        )
    )
    session.add(
        Supplier(
            id=_SUPPLIER_ID,
            name="ZZTEST Dash Supplier",
            category_focus="corrugated_packaging",
            unit_cost_tier=CostTier.MID,
            base_lead_time_days=7,
            lead_time_variability=Variability.LOW,
            historical_otif_pct=Decimal("90.00"),
        )
    )
    session.add(
        Carrier(
            id=_CARRIER_ID,
            name="ZZTEST Dash Carrier",
            transit_days_min=Decimal("1.0"),
            transit_days_max=Decimal("3.0"),
            variability=Variability.LOW,
            reliability_pct=Decimal("95.00"),
        )
    )
    session.flush()
    session.add(
        Customer(
            id=_CUSTOMER_ID,
            name="ZZTEST Dash Customer",
            service_priority=ServicePriority.STANDARD,
            warehouse_id=_WAREHOUSE_ID,
            region="Test Region",
        )
    )
    session.flush()

    # --- Purchase orders (Supplier view + Order/purchase view + at-risk) ---
    at_risk_po = PurchaseOrder(
        po_number=f"ZZTEST-PO-{uuid.uuid4().hex[:8]}",
        supplier_id=_SUPPLIER_ID,
        warehouse_id=_WAREHOUSE_ID,
        order_date=SIM_DATE - timedelta(days=10),
        expected_delivery_date=SIM_DATE - timedelta(days=3),  # past due -> at risk
        status=PurchaseOrderStatus.CONFIRMED,
        source_system=SourceSystem.PROCUREMENT,
    )
    session.add(at_risk_po)
    session.flush()
    session.add(
        PurchaseOrderLine(
            purchase_order_id=at_risk_po.id,
            product_id=_PRODUCT_ID,
            quantity_ordered=100,
            quantity_received=0,
            unit_cost=Decimal("2.50"),
        )
    )
    session.add(
        PurchaseOrderLifecycleEvent(
            purchase_order_id=at_risk_po.id,
            from_status=PurchaseOrderStatus.SUBMITTED,
            to_status=PurchaseOrderStatus.CONFIRMED,
            simulation_date=SIM_DATE - timedelta(days=9),
        )
    )

    closed_po = PurchaseOrder(
        po_number=f"ZZTEST-PO-{uuid.uuid4().hex[:8]}",
        supplier_id=_SUPPLIER_ID,
        warehouse_id=_WAREHOUSE_ID,
        order_date=SIM_DATE - timedelta(days=20),
        expected_delivery_date=SIM_DATE - timedelta(days=13),
        status=PurchaseOrderStatus.RECEIVED,
        source_system=SourceSystem.PROCUREMENT,
    )
    session.add(closed_po)
    session.flush()
    session.add(
        PurchaseOrderLine(
            purchase_order_id=closed_po.id,
            product_id=_PRODUCT_ID,
            quantity_ordered=50,
            quantity_received=50,
            unit_cost=Decimal("2.50"),
        )
    )

    at_risk_flag = ExceptionFlag(
        category=AT_RISK_PO_CATEGORY,
        purchase_order_id=at_risk_po.id,
        simulation_date=SIM_DATE,
        first_detected_simulation_date=SIM_DATE,
        measured_value=Decimal("3"),
        threshold_value=Decimal("0"),
    )
    session.add(at_risk_flag)

    # --- Sales orders + shipments (Order/sales view + OTIF/fill-rate) ---
    on_time_so = SalesOrder(
        so_number=f"ZZTEST-SO-{uuid.uuid4().hex[:8]}",
        customer_id=_CUSTOMER_ID,
        warehouse_id=_WAREHOUSE_ID,
        order_date=SIM_DATE - timedelta(days=15),
        requested_date=SIM_DATE - timedelta(days=12),
        promised_date=SIM_DATE - timedelta(days=10),
        status=SalesOrderStatus.SHIPPED,
        source_system=SourceSystem.ERP,
    )
    session.add(on_time_so)
    session.flush()
    session.add(
        SalesOrderLine(
            sales_order_id=on_time_so.id,
            product_id=_PRODUCT_ID,
            quantity_ordered=10,
            quantity_shipped=10,
            unit_price=Decimal("3.50"),
        )
    )
    on_time_shipment = Shipment(
        sales_order_id=on_time_so.id,
        carrier_id=_CARRIER_ID,
        warehouse_id=_WAREHOUSE_ID,
        ship_date=SIM_DATE - timedelta(days=11),
        promised_delivery_date=SIM_DATE - timedelta(days=9),
        actual_delivery_date=SIM_DATE - timedelta(days=9),
        status=ShipmentStatus.DELIVERED,
        source_system=SourceSystem.WMS,
    )
    session.add(on_time_shipment)

    late_so = SalesOrder(
        so_number=f"ZZTEST-SO-{uuid.uuid4().hex[:8]}",
        customer_id=_CUSTOMER_ID,
        warehouse_id=_WAREHOUSE_ID,
        order_date=SIM_DATE - timedelta(days=15),
        requested_date=SIM_DATE - timedelta(days=12),
        promised_date=SIM_DATE - timedelta(days=10),
        status=SalesOrderStatus.SHIPPED,
        source_system=SourceSystem.ERP,
    )
    session.add(late_so)
    session.flush()
    session.add(
        SalesOrderLine(
            sales_order_id=late_so.id,
            product_id=_PRODUCT_ID,
            quantity_ordered=10,
            quantity_shipped=10,
            unit_price=Decimal("3.50"),
        )
    )
    late_shipment = Shipment(
        sales_order_id=late_so.id,
        carrier_id=_CARRIER_ID,
        warehouse_id=_WAREHOUSE_ID,
        ship_date=SIM_DATE - timedelta(days=11),
        promised_delivery_date=SIM_DATE - timedelta(days=8),
        actual_delivery_date=SIM_DATE - timedelta(days=5),  # 3 days late
        status=ShipmentStatus.DELIVERED,
        source_system=SourceSystem.WMS,
    )
    session.add(late_shipment)
    session.flush()

    late_flag = ExceptionFlag(
        category=LATE_SHIPMENT_CATEGORY,
        shipment_id=late_shipment.id,
        simulation_date=SIM_DATE,
        first_detected_simulation_date=SIM_DATE,
        measured_value=Decimal("3"),
        threshold_value=Decimal("0"),
    )
    session.add(late_flag)

    # --- Inventory (Inventory view + low-stock exception) ---
    session.add(
        InventorySnapshot(
            snapshot_date=SIM_DATE,
            product_id=_PRODUCT_ID,
            warehouse_id=_WAREHOUSE_ID,
            quantity_on_hand=5,
            quantity_allocated=0,
            source_system=SourceSystem.WMS,
        )
    )
    txn1 = InventoryTransaction(
        transaction_at=SIM_DATE - timedelta(days=2),
        product_id=_PRODUCT_ID,
        warehouse_id=_WAREHOUSE_ID,
        transaction_type=InventoryTransactionType.RECEIPT,
        quantity_delta=50,
        source_system=SourceSystem.PROCUREMENT,
    )
    txn2 = InventoryTransaction(
        transaction_at=SIM_DATE - timedelta(days=1),
        product_id=_PRODUCT_ID,
        warehouse_id=_WAREHOUSE_ID,
        transaction_type=InventoryTransactionType.SHIPMENT,
        quantity_delta=-45,
        source_system=SourceSystem.WMS,
    )
    session.add(txn1)
    session.add(txn2)
    session.flush()

    low_stock_flag = ExceptionFlag(
        category=LOW_STOCK_CATEGORY,
        product_id=_PRODUCT_ID,
        warehouse_id=_WAREHOUSE_ID,
        simulation_date=SIM_DATE,
        first_detected_simulation_date=SIM_DATE,
        measured_value=Decimal("2.0"),
        threshold_value=Decimal("14"),
    )
    session.add(low_stock_flag)
    session.flush()

    # A second, earlier KpiSnapshot row purely for the pagination tests
    # (security review, MEDIUM: /executive/trend was unbounded) — inserted
    # directly, not via compute_and_snapshot_kpis, since it's earlier than
    # SIM_DATE and that function's own out-of-order guard (Unit 14) would
    # reject computing an earlier date after this fixture's later one.
    earlier_kpi_snapshot = KpiSnapshot(
        simulation_date=SIM_DATE - timedelta(days=1),
        otif_pct=Decimal("40.00"),
        fill_rate_pct=Decimal("90.00"),
        order_cycle_time_days=Decimal("5.0"),
        perfect_order_rate_pct=Decimal("40.00"),
    )
    session.add(earlier_kpi_snapshot)
    session.flush()

    # KpiSnapshot via the real engine (Unit 14) — ties this fixture's
    # expected OTIF/fill-rate/etc. to production logic, not a hand-typed
    # duplicate of otif.sql's math. Its own days_of_supply_snapshot upsert
    # recomputes real days_of_supply.sql against the *actual* global
    # simulation_clock date (not SIM_DATE, which is 73 years in the future
    # purely to dodge KpiSnapshot's global out-of-order guard) — this
    # product/warehouse's fixture transactions fall outside that real
    # 30-day window, so the recompute would write NULL for this pair.
    # Insert the fixture's own known days-of-supply value AFTER, so it's
    # the row this test actually reads, not a NULL the KPI engine's
    # unrelated recompute silently overwrote it with.
    compute_and_snapshot_kpis(session, SIM_DATE)
    # compute_and_snapshot_kpis's own upsert already created this exact
    # (simulation_date, product_id, warehouse_id) row — mutate it in place
    # rather than inserting a second one (would violate its unique
    # constraint).
    dos_row = session.execute(
        select(DaysOfSupplySnapshot).where(
            DaysOfSupplySnapshot.simulation_date == SIM_DATE,
            DaysOfSupplySnapshot.product_id == _PRODUCT_ID,
            DaysOfSupplySnapshot.warehouse_id == _WAREHOUSE_ID,
        )
    ).scalar_one()
    dos_row.days_of_supply = Decimal("2.0")
    session.flush()
    session.commit()

    yield _Scenario(
        at_risk_po_id=at_risk_po.id,
        closed_po_id=closed_po.id,
        on_time_so_id=on_time_so.id,
        late_so_id=late_so.id,
        on_time_shipment_id=on_time_shipment.id,
        late_shipment_id=late_shipment.id,
        at_risk_flag_id=at_risk_flag.id,
        late_flag_id=late_flag.id,
        low_stock_flag_id=low_stock_flag.id,
        inventory_transaction_ids=[txn1.id, txn2.id],
    )

    db_session.execute(
        delete(InventoryTransaction).where(InventoryTransaction.product_id == _PRODUCT_ID)
    )
    db_session.execute(delete(ExceptionFlag).where(ExceptionFlag.product_id == _PRODUCT_ID))
    db_session.execute(
        delete(ExceptionFlag).where(ExceptionFlag.purchase_order_id == at_risk_po.id)
    )
    db_session.execute(delete(ExceptionFlag).where(ExceptionFlag.shipment_id == late_shipment.id))
    db_session.execute(delete(Shipment).where(Shipment.warehouse_id == _WAREHOUSE_ID))
    db_session.execute(delete(SalesOrderLifecycleEvent).where(SalesOrderLifecycleEvent.sales_order_id.in_([on_time_so.id, late_so.id])))
    db_session.execute(delete(SalesOrderLine).where(SalesOrderLine.product_id == _PRODUCT_ID))
    db_session.execute(delete(SalesOrder).where(SalesOrder.warehouse_id == _WAREHOUSE_ID))
    db_session.execute(delete(PurchaseOrderLifecycleEvent).where(PurchaseOrderLifecycleEvent.purchase_order_id == at_risk_po.id))
    db_session.execute(delete(PurchaseOrderLine).where(PurchaseOrderLine.product_id == _PRODUCT_ID))
    db_session.execute(delete(PurchaseOrder).where(PurchaseOrder.warehouse_id == _WAREHOUSE_ID))
    db_session.execute(delete(InventorySnapshot).where(InventorySnapshot.product_id == _PRODUCT_ID))
    db_session.execute(delete(DaysOfSupplySnapshot).where(DaysOfSupplySnapshot.product_id == _PRODUCT_ID))
    db_session.execute(
        delete(KpiSnapshot).where(
            KpiSnapshot.simulation_date.in_([SIM_DATE, SIM_DATE - timedelta(days=1)])
        )
    )
    db_session.execute(delete(Customer).where(Customer.id == _CUSTOMER_ID))
    db_session.execute(delete(Carrier).where(Carrier.id == _CARRIER_ID))
    db_session.execute(delete(Product).where(Product.id == _PRODUCT_ID))
    db_session.execute(delete(Supplier).where(Supplier.id == _SUPPLIER_ID))
    db_session.execute(delete(Warehouse).where(Warehouse.id == _WAREHOUSE_ID))
    db_session.commit()


class TestAuthRequired:
    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/dashboard/executive",
            "/api/v1/dashboard/executive/trend",
            "/api/v1/dashboard/inventory",
            f"/api/v1/dashboard/inventory/{_PRODUCT_ID}/{_WAREHOUSE_ID}/transactions",
            "/api/v1/dashboard/suppliers",
            f"/api/v1/dashboard/suppliers/{_SUPPLIER_ID}/purchase-orders",
            "/api/v1/dashboard/orders/purchase",
            f"/api/v1/dashboard/orders/purchase/{uuid.uuid4()}",
            "/api/v1/dashboard/orders/sales",
            f"/api/v1/dashboard/orders/sales/{uuid.uuid4()}",
            "/api/v1/dashboard/shipments",
            "/api/v1/dashboard/exceptions",
            f"/api/v1/dashboard/exceptions/{uuid.uuid4()}",
        ],
    )
    def test_requires_auth(self, client: TestClient, path: str) -> None:
        response = client.get(path)
        assert response.status_code == 401

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/dashboard/executive",
            "/api/v1/dashboard/executive/trend",
            "/api/v1/dashboard/inventory",
            "/api/v1/dashboard/suppliers",
            "/api/v1/dashboard/orders/purchase",
            "/api/v1/dashboard/orders/sales",
            "/api/v1/dashboard/shipments",
            "/api/v1/dashboard/exceptions",
        ],
    )
    def test_is_reachable_by_the_analyst_role(self, client: TestClient, path: str) -> None:
        # Unit 17a (MEADOWOPS-DOM-010, DD-22): Analyst can view everything
        # Subsystem 1 exposes. Only the list-shaped routes (no path params
        # pointing at fixture rows that don't exist in this class's own
        # scope) — a 404 on a made-up id would be a false failure signal
        # here, since it proves nothing about the auth layer either way.
        response = client.get(path, headers=_ANALYST_AUTH)
        assert response.status_code == 200


class TestExecutiveView:
    def test_summary_reflects_the_latest_kpi_snapshot_and_open_exception_counts(
        self, client: TestClient, scenario: _Scenario
    ) -> None:
        response = client.get("/api/v1/dashboard/executive", headers=_AUTH)
        assert response.status_code == 200
        body = response.json()
        assert body["kpis"]["simulation_date"] == SIM_DATE.isoformat()
        # Reconciliation: 2 delivered sales orders, 1 on-time+in-full, 1
        # late -> OTIF and perfect-order-rate are both 50.00; fill rate is
        # 100 (both fully shipped); order cycle time averages 6 and 10 days.
        assert body["kpis"]["otif_pct"] == "50.00"
        assert body["kpis"]["perfect_order_rate_pct"] == "50.00"
        assert body["kpis"]["fill_rate_pct"] == "100.00"
        assert body["kpis"]["order_cycle_time_days"] == "8.0"
        counts = {row["category"]: row["open_count"] for row in body["open_exception_counts"]}
        assert counts[AT_RISK_PO_CATEGORY] >= 1
        assert counts[LATE_SHIPMENT_CATEGORY] >= 1
        assert counts[LOW_STOCK_CATEGORY] >= 1

    def test_trend_includes_the_same_row_the_summary_reports_as_latest(
        self, client: TestClient, scenario: _Scenario
    ) -> None:
        summary = client.get("/api/v1/dashboard/executive", headers=_AUTH).json()
        trend = client.get("/api/v1/dashboard/executive/trend", headers=_AUTH).json()
        matching = [row for row in trend if row["simulation_date"] == SIM_DATE.isoformat()]
        assert len(matching) == 1
        assert matching[0]["otif_pct"] == summary["kpis"]["otif_pct"]

    def test_otif_reconciles_against_the_underlying_sales_order_drilldown(
        self, client: TestClient, scenario: _Scenario
    ) -> None:
        """The discriminating reconciliation test (spec id 207): recomputes
        OTIF from nothing but the /orders/sales list + per-order drill-down
        responses, independent of the stored KpiSnapshot row, and confirms
        it matches what /executive reports."""
        summary = client.get("/api/v1/dashboard/executive", headers=_AUTH).json()
        orders = client.get(
            "/api/v1/dashboard/orders/sales", params={"warehouse_id": _WAREHOUSE_ID}, headers=_AUTH
        ).json()
        assert {o["id"] for o in orders} == {str(scenario.on_time_so_id), str(scenario.late_so_id)}

        qualifying = 0
        on_time_in_full = 0
        for order in orders:
            detail = client.get(
                f"/api/v1/dashboard/orders/sales/{order['id']}", headers=_AUTH
            ).json()
            delivered_shipments = [s for s in detail["shipments"] if s["status"] == "delivered"]
            if not delivered_shipments:
                continue
            qualifying += 1
            in_full = all(
                line["quantity_shipped"] >= line["quantity_ordered"] for line in detail["lines"]
            )
            on_time = any(not s["is_late"] for s in delivered_shipments)
            if in_full and on_time:
                on_time_in_full += 1

        recomputed_otif_pct = round(100.0 * on_time_in_full / qualifying, 2)
        assert f"{recomputed_otif_pct:.2f}" == summary["kpis"]["otif_pct"]

    def test_trend_respects_limit_and_returns_the_most_recent_rows(
        self, client: TestClient, scenario: _Scenario
    ) -> None:
        """Security review (MEDIUM): /executive/trend previously returned
        every KpiSnapshot row ever written, unbounded — grows one row per
        scheduler tick indefinitely."""
        response = client.get(
            "/api/v1/dashboard/executive/trend", params={"limit": 1}, headers=_AUTH
        )
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 1
        # The most recent row, not an arbitrary one — this fixture's two
        # KpiSnapshot rows are SIM_DATE and SIM_DATE - 1 day.
        assert rows[0]["simulation_date"] == SIM_DATE.isoformat()


class TestInventoryView:
    def test_low_stock_row_matches_the_fixture_and_is_flagged(
        self, client: TestClient, scenario: _Scenario
    ) -> None:
        response = client.get(
            "/api/v1/dashboard/inventory", params={"warehouse_id": _WAREHOUSE_ID}, headers=_AUTH
        )
        assert response.status_code == 200
        rows = response.json()
        row = next(r for r in rows if r["product_id"] == _PRODUCT_ID)
        assert row["quantity_on_hand"] == 5
        assert row["days_of_supply"] == "2.0"
        assert row["is_low_stock"] is True

    def test_transactions_drilldown_reconciles_to_the_on_hand_quantity(
        self, client: TestClient, scenario: _Scenario
    ) -> None:
        response = client.get(
            f"/api/v1/dashboard/inventory/{_PRODUCT_ID}/{_WAREHOUSE_ID}/transactions",
            headers=_AUTH,
        )
        assert response.status_code == 200
        rows = response.json()
        assert {r["id"] for r in rows} == {str(i) for i in scenario.inventory_transaction_ids}
        # Reconciliation: the two transactions net to the snapshot's
        # quantity_on_hand (50 receipt, 45 shipped out -> 5 on hand).
        assert sum(r["quantity_delta"] for r in rows) == 5

    def test_unknown_product_returns_404(self, client: TestClient) -> None:
        response = client.get(
            f"/api/v1/dashboard/inventory/NOPE/{_WAREHOUSE_ID}/transactions", headers=_AUTH
        )
        assert response.status_code == 404

    def test_filters_narrow_to_exactly_one_row(
        self, client: TestClient, scenario: _Scenario
    ) -> None:
        """Security review (MEDIUM): warehouse_id/product_id were filtered
        in a Python list comprehension after loading every
        DaysOfSupplySnapshot/InventorySnapshot row into memory — the
        .where() filters never reached the DB query. Filtering down to
        exactly this fixture's one row is the externally-observable proof
        the fix pushes the filter into the query (the internal query-plan
        change itself isn't black-box testable, but this pins the
        contract: a filtered request must return only matching rows, not
        rely on the caller re-filtering client-side)."""
        response = client.get(
            "/api/v1/dashboard/inventory",
            params={"warehouse_id": _WAREHOUSE_ID, "product_id": _PRODUCT_ID},
            headers=_AUTH,
        )
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 1
        assert rows[0]["product_id"] == _PRODUCT_ID
        assert rows[0]["warehouse_id"] == _WAREHOUSE_ID


class TestSupplierView:
    def test_counts_reconcile_against_the_purchase_order_fixture(
        self, client: TestClient, scenario: _Scenario
    ) -> None:
        response = client.get("/api/v1/dashboard/suppliers", headers=_AUTH)
        assert response.status_code == 200
        row = next(r for r in response.json() if r["supplier_id"] == _SUPPLIER_ID)
        assert row["total_purchase_order_count"] == 2
        assert row["open_purchase_order_count"] == 1  # CONFIRMED only; RECEIVED is closed
        assert row["at_risk_purchase_order_count"] == 1

    def test_drilldown_lists_exactly_this_supplier_s_purchase_orders(
        self, client: TestClient, scenario: _Scenario
    ) -> None:
        response = client.get(
            f"/api/v1/dashboard/suppliers/{_SUPPLIER_ID}/purchase-orders", headers=_AUTH
        )
        assert response.status_code == 200
        ids = {row["id"] for row in response.json()}
        assert ids == {str(scenario.at_risk_po_id), str(scenario.closed_po_id)}
        at_risk_row = next(r for r in response.json() if r["id"] == str(scenario.at_risk_po_id))
        assert at_risk_row["is_at_risk"] is True
        closed_row = next(r for r in response.json() if r["id"] == str(scenario.closed_po_id))
        assert closed_row["is_at_risk"] is False

    def test_unknown_supplier_returns_404(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/dashboard/suppliers/ZZTEST-NOPE/purchase-orders", headers=_AUTH
        )
        assert response.status_code == 404

    def test_drilldown_respects_limit_and_offset(
        self, client: TestClient, scenario: _Scenario
    ) -> None:
        """Security review (MEDIUM): unbounded result set. The fixture's
        at_risk_po (order_date SIM_DATE-10) sorts before closed_po
        (order_date SIM_DATE-20) under the endpoint's own desc ordering."""
        first_page = client.get(
            f"/api/v1/dashboard/suppliers/{_SUPPLIER_ID}/purchase-orders",
            params={"limit": 1, "offset": 0},
            headers=_AUTH,
        ).json()
        assert len(first_page) == 1
        assert first_page[0]["id"] == str(scenario.at_risk_po_id)

        second_page = client.get(
            f"/api/v1/dashboard/suppliers/{_SUPPLIER_ID}/purchase-orders",
            params={"limit": 1, "offset": 1},
            headers=_AUTH,
        ).json()
        assert len(second_page) == 1
        assert second_page[0]["id"] == str(scenario.closed_po_id)


class TestOrderViews:
    def test_purchase_order_detail_includes_lines_and_lifecycle_and_is_at_risk(
        self, client: TestClient, scenario: _Scenario
    ) -> None:
        response = client.get(
            f"/api/v1/dashboard/orders/purchase/{scenario.at_risk_po_id}", headers=_AUTH
        )
        assert response.status_code == 200
        body = response.json()
        assert body["is_at_risk"] is True
        assert sum(line["quantity_ordered"] for line in body["lines"]) == 100
        assert len(body["lifecycle_events"]) == 1

    def test_sales_order_detail_includes_its_shipment(
        self, client: TestClient, scenario: _Scenario
    ) -> None:
        response = client.get(
            f"/api/v1/dashboard/orders/sales/{scenario.late_so_id}", headers=_AUTH
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["shipments"]) == 1
        assert body["shipments"][0]["is_late"] is True

    def test_shipments_list_reconciles_against_the_sales_order_drilldowns(
        self, client: TestClient, scenario: _Scenario
    ) -> None:
        response = client.get(
            "/api/v1/dashboard/shipments", params={"warehouse_id": _WAREHOUSE_ID}, headers=_AUTH
        )
        assert response.status_code == 200
        rows = response.json()
        ids = {row["id"] for row in rows}
        assert ids == {str(scenario.on_time_shipment_id), str(scenario.late_shipment_id)}
        late_row = next(r for r in rows if r["id"] == str(scenario.late_shipment_id))
        assert late_row["is_late"] is True
        on_time_row = next(r for r in rows if r["id"] == str(scenario.on_time_shipment_id))
        assert on_time_row["is_late"] is False

    def test_unknown_purchase_order_returns_404(self, client: TestClient) -> None:
        response = client.get(f"/api/v1/dashboard/orders/purchase/{uuid.uuid4()}", headers=_AUTH)
        assert response.status_code == 404

    def test_purchase_orders_list_respects_limit_and_offset(
        self, client: TestClient, scenario: _Scenario
    ) -> None:
        """Security review (MEDIUM): unbounded result set."""
        first_page = client.get(
            "/api/v1/dashboard/orders/purchase",
            params={"warehouse_id": _WAREHOUSE_ID, "limit": 1, "offset": 0},
            headers=_AUTH,
        ).json()
        assert len(first_page) == 1
        assert first_page[0]["id"] == str(scenario.at_risk_po_id)

        second_page = client.get(
            "/api/v1/dashboard/orders/purchase",
            params={"warehouse_id": _WAREHOUSE_ID, "limit": 1, "offset": 1},
            headers=_AUTH,
        ).json()
        assert len(second_page) == 1
        assert second_page[0]["id"] == str(scenario.closed_po_id)

    def test_sales_orders_list_respects_limit(
        self, client: TestClient, scenario: _Scenario
    ) -> None:
        """Security review (MEDIUM): unbounded result set. The fixture's two
        sales orders share an order_date, so only the count is pinned here —
        exact tie-break ordering isn't a contract this endpoint makes."""
        response = client.get(
            "/api/v1/dashboard/orders/sales",
            params={"warehouse_id": _WAREHOUSE_ID, "limit": 1},
            headers=_AUTH,
        )
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_shipments_list_respects_limit(
        self, client: TestClient, scenario: _Scenario
    ) -> None:
        """Security review (MEDIUM): unbounded result set."""
        response = client.get(
            "/api/v1/dashboard/shipments",
            params={"warehouse_id": _WAREHOUSE_ID, "limit": 1},
            headers=_AUTH,
        )
        assert response.status_code == 200
        assert len(response.json()) == 1


class TestExceptionsView:
    def test_default_listing_shows_only_open_flags_from_this_fixture(
        self, client: TestClient, scenario: _Scenario
    ) -> None:
        response = client.get(
            "/api/v1/dashboard/exceptions",
            params={"category": LOW_STOCK_CATEGORY},
            headers=_AUTH,
        )
        assert response.status_code == 200
        ids = {row["id"] for row in response.json()}
        assert str(scenario.low_stock_flag_id) in ids
        assert all(row["resolved_at"] is None for row in response.json())

    def test_open_exception_count_reconciles_against_the_executive_summary(
        self, client: TestClient, scenario: _Scenario
    ) -> None:
        summary = client.get("/api/v1/dashboard/executive", headers=_AUTH).json()
        exceptions = client.get(
            "/api/v1/dashboard/exceptions",
            params={"category": AT_RISK_PO_CATEGORY},
            headers=_AUTH,
        ).json()
        counts = {row["category"]: row["open_count"] for row in summary["open_exception_counts"]}
        assert counts[AT_RISK_PO_CATEGORY] == len(exceptions)

    def test_drilldown_from_an_at_risk_po_flag_returns_that_purchase_order(
        self, client: TestClient, scenario: _Scenario
    ) -> None:
        response = client.get(
            f"/api/v1/dashboard/exceptions/{scenario.at_risk_flag_id}", headers=_AUTH
        )
        assert response.status_code == 200
        body = response.json()
        assert body["purchase_order"]["id"] == str(scenario.at_risk_po_id)
        assert body["shipment"] is None
        assert body["inventory"] is None

    def test_drilldown_from_a_low_stock_flag_returns_the_inventory_position(
        self, client: TestClient, scenario: _Scenario
    ) -> None:
        response = client.get(
            f"/api/v1/dashboard/exceptions/{scenario.low_stock_flag_id}", headers=_AUTH
        )
        assert response.status_code == 200
        body = response.json()
        assert body["inventory"]["product_id"] == _PRODUCT_ID
        assert body["inventory"]["is_low_stock"] is True
        assert body["purchase_order"] is None

    def test_unknown_flag_returns_404(self, client: TestClient) -> None:
        response = client.get(f"/api/v1/dashboard/exceptions/{uuid.uuid4()}", headers=_AUTH)
        assert response.status_code == 404

    def test_listing_respects_limit(self, client: TestClient, scenario: _Scenario) -> None:
        """Security review (MEDIUM): unbounded result set. This fixture's
        three flags share a detected_at, so only the count is pinned here."""
        response = client.get(
            "/api/v1/dashboard/exceptions", params={"limit": 1}, headers=_AUTH
        )
        assert response.status_code == 200
        assert len(response.json()) == 1
