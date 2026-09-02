"""Unit 2 (MEADOWOPS-DATA-001): core star schema — dimensions + operational
facts in the `live` schema, each fact tagged with source_system (PRD 4.1).

Edge case catalog (PRD 9.2) rows covered here:
- #3 Negative inventory quantities rejected at the write boundary.
"""

import psycopg
import pytest

DIMENSION_TABLES = {"product", "warehouse", "supplier", "customer", "carrier", "date_dim"}
FACT_TABLES = {
    "inventory_snapshot",
    "inventory_transaction",
    "purchase_order",
    "purchase_order_line",
    "sales_order",
    "sales_order_line",
    "shipment",
    "warehouse_transfer",
}
SOURCE_TAGGED_FACTS = {
    "inventory_snapshot",
    "inventory_transaction",
    "purchase_order",
    "sales_order",
    "shipment",
    "warehouse_transfer",
}


def _tables_in_live_schema(owner_dsn: str) -> set[str]:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select table_name from information_schema.tables where table_schema = 'live'"
        )
        return {row[0] for row in cur.fetchall()}


def test_all_dimension_and_fact_tables_exist(owner_dsn: str) -> None:
    found = _tables_in_live_schema(owner_dsn)
    missing = (DIMENSION_TABLES | FACT_TABLES) - found
    assert not missing, f"missing tables in live schema: {missing}"


@pytest.mark.parametrize("table", sorted(SOURCE_TAGGED_FACTS))
def test_fact_table_has_source_system_column(owner_dsn: str, table: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select column_name from information_schema.columns "
            "where table_schema = 'live' and table_name = %s and column_name = 'source_system'",
            (table,),
        )
        assert cur.fetchone() is not None, f"{table} is missing source_system"


def test_inventory_snapshot_rejects_negative_quantity_on_hand(owner_dsn: str) -> None:
    # Not autocommitted, rolled back at the end (DD-10): these `TEST`-suffixed
    # rows were previously committed permanently into the shared dev
    # database with no cleanup at all, and stayed there undetected across
    # eight later units until Unit 10's KPI SQL started aggregating over
    # `live.warehouse`/`live.supplier` and surfaced a phantom "Test
    # Warehouse"/"Test Supplier" in the results.
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "insert into live.product (id, sku, name, category, unit_cost, is_active) "
            "values ('SKU-TEST-001', 'SKU-TEST-001', 'Test Product', 'corrugated_packaging', 1.00, true)"
        )
        cur.execute(
            "insert into live.warehouse (id, name, region, capacity_pallet_positions, is_active) "
            "values ('WH-TEST', 'Test Warehouse', 'Test Region', 100, true)"
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "insert into live.inventory_snapshot "
                "(id, snapshot_date, product_id, warehouse_id, quantity_on_hand, "
                "quantity_allocated, source_system) "
                "values (gen_random_uuid(), current_date, 'SKU-TEST-001', 'WH-TEST', "
                "-5, 0, 'erp')"
            )
        conn.rollback()


def test_purchase_order_line_rejects_negative_quantity_received(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "insert into live.supplier (id, name, category_focus, unit_cost_tier, "
            "base_lead_time_days, lead_time_variability, historical_otif_pct, is_active) "
            "values ('S-TEST', 'Test Supplier', 'Test', 'mid', 7, 'low', 95.0, true)"
        )
        cur.execute(
            "insert into live.warehouse (id, name, region, capacity_pallet_positions, is_active) "
            "values ('WH-TEST', 'Test Warehouse', 'Test Region', 100, true)"
        )
        cur.execute(
            "insert into live.purchase_order "
            "(id, po_number, supplier_id, warehouse_id, order_date, "
            "expected_delivery_date, status, source_system) "
            "values (gen_random_uuid(), 'PO-TEST-001', 'S-TEST', 'WH-TEST', "
            "current_date, current_date, 'submitted', 'procurement') "
            "returning id"
        )
        (po_id,) = cur.fetchone()
        cur.execute(
            "insert into live.product (id, sku, name, category, unit_cost, is_active) "
            "values ('SKU-TEST-001', 'SKU-TEST-001', 'Test Product', 'corrugated_packaging', 1.00, true)"
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "insert into live.purchase_order_line "
                "(id, purchase_order_id, product_id, quantity_ordered, "
                "quantity_received, unit_cost) "
                "values (gen_random_uuid(), %s, 'SKU-TEST-001', 10, -1, 1.00)",
                (po_id,),
            )
        conn.rollback()


def test_shipment_orphaned_sales_order_reference_is_rejected_by_default(owner_dsn: str) -> None:
    """Baseline referential integrity: a live FK constraint blocks an
    orphaned reference outright. Bad-data *injection* for edge case #1
    (an orphaned FK slipping past normal writes) is a controlled mechanism
    implemented in the SR-1..4 unit (U17) — this test only proves the
    default, non-injected path is a real constraint, not that injection is
    impossible."""
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "insert into live.carrier (id, name, transit_days_min, transit_days_max, "
            "variability, reliability_pct, is_active) "
            "values ('C-TEST', 'Test Carrier', 2, 3, 'low', 98.0, true)"
        )
        cur.execute(
            "insert into live.warehouse (id, name, region, capacity_pallet_positions, is_active) "
            "values ('WH-TEST', 'Test Warehouse', 'Test Region', 100, true)"
        )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cur.execute(
                "insert into live.shipment "
                "(id, sales_order_id, carrier_id, warehouse_id, ship_date, "
                "promised_delivery_date, status, source_system) "
                "values (gen_random_uuid(), gen_random_uuid(), 'C-TEST', 'WH-TEST', "
                "current_date, current_date, 'pending', 'wms')"
            )
        conn.rollback()
