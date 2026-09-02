"""Tests for the starter KPI SQL (PRD Appendix A, S1-FR-3/S1-FR-11, spec
MEADOWOPS-DOMAIN-004).

These are Builder-set placeholders pending Analyst review (PRD line 207),
not final calculations - Unit 14 (MEADOWOPS-DOMAIN-006) is the real KPI
engine. What's tested here: each query loads, executes without error
against the actual seeded schema, degrades gracefully (NULL/zero rows, never
an exception) when the relevant fact tables are empty (true of the current
baseline seed - Unit 5 seeds only master data), and - the part that actually
proves the SQL is correct rather than merely well-formed - produces the
right number against a small set of hand-crafted, rolled-back rows.
"""

from datetime import date, timedelta

import psycopg
import pytest

from app.domain.kpi_sql import KPI_NAMES, load_kpi_sql


class TestLoadKpiSql:
    @pytest.mark.parametrize("name", KPI_NAMES)
    def test_loads_non_empty_sql_text_for_each_known_kpi(self, name: str) -> None:
        sql = load_kpi_sql(name)
        assert sql.strip()

    def test_raises_for_an_unknown_kpi_name(self) -> None:
        with pytest.raises(ValueError):
            load_kpi_sql("not_a_real_kpi")


class TestStarterKpiSqlExecutesAgainstSeededSchema:
    """The current baseline seed (Unit 5) has zero rows in every
    transactional fact table these queries read - real order/shipment
    history doesn't exist until Unit 13. Each of these therefore also proves
    the NULLIF/empty-input guarding actually works, not just that the SQL
    parses."""

    @pytest.mark.parametrize("name", KPI_NAMES)
    def test_query_executes_without_raising(self, owner_dsn: str, name: str) -> None:
        with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
            cur.execute(load_kpi_sql(name))
            cur.fetchall()

    def test_otif_is_null_with_no_delivered_shipments(self, owner_dsn: str) -> None:
        with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
            cur.execute(load_kpi_sql("otif"))
            (row,) = cur.fetchall()
        assert row == (None,)

    def test_perfect_order_rate_is_null_with_no_delivered_shipments(
        self, owner_dsn: str
    ) -> None:
        with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
            cur.execute(load_kpi_sql("perfect_order_rate"))
            (row,) = cur.fetchall()
        assert row == (None,)

    def test_fill_rate_is_null_with_no_order_lines(self, owner_dsn: str) -> None:
        with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
            cur.execute(load_kpi_sql("fill_rate"))
            (row,) = cur.fetchall()
        assert row == (None,)

    def test_order_cycle_time_is_null_with_no_delivered_shipments(
        self, owner_dsn: str
    ) -> None:
        with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
            cur.execute(load_kpi_sql("order_cycle_time"))
            (row,) = cur.fetchall()
        assert row == (None,)

    def test_days_of_supply_returns_no_rows_with_no_inventory_snapshot(
        self, owner_dsn: str
    ) -> None:
        # Different degradation shape than the others (documented in
        # days_of_supply.sql): it's driven by a per-product/warehouse CTE,
        # so an empty snapshot table means zero output rows, not one row of
        # NULLs.
        with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
            cur.execute(load_kpi_sql("days_of_supply"))
            rows = cur.fetchall()
        assert rows == []


class TestOtifSemanticCorrectness:
    """Hand-crafted, rolled-back rows against real master data (real
    product/customer/warehouse/carrier ids) - proves the SQL computes the
    right number, not just that it runs. Not autocommitted (DD-10)."""

    def test_on_time_in_full_delivered_order_counts_as_otif(
        self, owner_dsn: str
    ) -> None:
        with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "insert into live.sales_order "
                "(id, so_number, customer_id, warehouse_id, order_date, "
                "requested_date, status, source_system) "
                "values (gen_random_uuid(), 'ZZTEST-SO-OTIF-01', 'CUST-EAST-01', "
                "'WH-EAST', current_date - 5, current_date, 'shipped', 'erp') "
                "returning id"
            )
            (so_id,) = cur.fetchone()
            cur.execute(
                "insert into live.sales_order_line "
                "(id, sales_order_id, product_id, quantity_ordered, "
                "quantity_shipped, unit_price) "
                "values (gen_random_uuid(), %s, 'SKU-COR-001', 10, 10, 5.00)",
                (so_id,),
            )
            cur.execute(
                "insert into live.shipment "
                "(id, sales_order_id, carrier_id, warehouse_id, ship_date, "
                "promised_delivery_date, actual_delivery_date, status, source_system) "
                "values (gen_random_uuid(), %s, 'C-001', 'WH-EAST', "
                "current_date - 3, current_date - 1, current_date - 1, "
                "'delivered', 'erp')",
                (so_id,),
            )
            cur.execute(load_kpi_sql("otif"))
            (row,) = cur.fetchall()
            conn.rollback()
        assert row == (100.0,)

    def test_late_delivery_is_excluded_from_otif(self, owner_dsn: str) -> None:
        with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "insert into live.sales_order "
                "(id, so_number, customer_id, warehouse_id, order_date, "
                "requested_date, status, source_system) "
                "values (gen_random_uuid(), 'ZZTEST-SO-OTIF-02', 'CUST-EAST-01', "
                "'WH-EAST', current_date - 5, current_date, 'shipped', 'erp') "
                "returning id"
            )
            (so_id,) = cur.fetchone()
            cur.execute(
                "insert into live.sales_order_line "
                "(id, sales_order_id, product_id, quantity_ordered, "
                "quantity_shipped, unit_price) "
                "values (gen_random_uuid(), %s, 'SKU-COR-001', 10, 10, 5.00)",
                (so_id,),
            )
            cur.execute(
                # Delivered a day AFTER the promised date - late.
                "insert into live.shipment "
                "(id, sales_order_id, carrier_id, warehouse_id, ship_date, "
                "promised_delivery_date, actual_delivery_date, status, source_system) "
                "values (gen_random_uuid(), %s, 'C-001', 'WH-EAST', "
                "current_date - 3, current_date - 2, current_date - 1, "
                "'delivered', 'erp')",
                (so_id,),
            )
            cur.execute(load_kpi_sql("otif"))
            (row,) = cur.fetchall()
            conn.rollback()
        assert row == (0.0,)

    def test_partial_shipment_is_excluded_from_otif(self, owner_dsn: str) -> None:
        with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "insert into live.sales_order "
                "(id, so_number, customer_id, warehouse_id, order_date, "
                "requested_date, status, source_system) "
                "values (gen_random_uuid(), 'ZZTEST-SO-OTIF-03', 'CUST-EAST-01', "
                "'WH-EAST', current_date - 5, current_date, 'partially_shipped', 'erp') "
                "returning id"
            )
            (so_id,) = cur.fetchone()
            cur.execute(
                # Ordered 10, shipped only 6 - not in full.
                "insert into live.sales_order_line "
                "(id, sales_order_id, product_id, quantity_ordered, "
                "quantity_shipped, unit_price) "
                "values (gen_random_uuid(), %s, 'SKU-COR-001', 10, 6, 5.00)",
                (so_id,),
            )
            cur.execute(
                "insert into live.shipment "
                "(id, sales_order_id, carrier_id, warehouse_id, ship_date, "
                "promised_delivery_date, actual_delivery_date, status, source_system) "
                "values (gen_random_uuid(), %s, 'C-001', 'WH-EAST', "
                "current_date - 3, current_date - 1, current_date - 1, "
                "'delivered', 'erp')",
                (so_id,),
            )
            cur.execute(load_kpi_sql("otif"))
            (row,) = cur.fetchall()
            conn.rollback()
        assert row == (0.0,)


class TestFillRateSemanticCorrectness:
    def test_half_shipped_quantity_yields_fifty_percent(self, owner_dsn: str) -> None:
        with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "insert into live.sales_order "
                "(id, so_number, customer_id, warehouse_id, order_date, "
                "requested_date, status, source_system) "
                "values (gen_random_uuid(), 'ZZTEST-SO-FILL-01', 'CUST-EAST-01', "
                "'WH-EAST', current_date - 5, current_date, 'partially_shipped', 'erp') "
                "returning id"
            )
            (so_id,) = cur.fetchone()
            cur.execute(
                "insert into live.sales_order_line "
                "(id, sales_order_id, product_id, quantity_ordered, "
                "quantity_shipped, unit_price) "
                "values (gen_random_uuid(), %s, 'SKU-COR-001', 20, 10, 5.00)",
                (so_id,),
            )
            cur.execute(load_kpi_sql("fill_rate"))
            (row,) = cur.fetchall()
            conn.rollback()
        assert row == (50.0,)


class TestDaysOfSupplySemanticCorrectness:
    """Every simulation_date here is deliberately offset from wall-clock
    time (60 simulated days in the past) and every transaction_at is
    stamped relative to THAT offset, not to real `now()` (security review,
    Unit 10): a test that anchors both to wall-clock time can't tell a
    correct simulation_date-based query apart from a buggy CURRENT_DATE-
    based one, since a naive substitution would pass identically. Anchoring
    the fixture data away from wall-clock time makes that substitution bug
    actually fail these tests, and test_ignores_wall_clock_time_entirely
    checks it directly."""

    def test_computes_usable_inventory_over_average_daily_usage(
        self, owner_dsn: str
    ) -> None:
        # 100 on hand, 20 allocated -> 80 usable. 60 units shipped (as
        # negative quantity_delta) 2 simulated days before a simulation_date
        # that is itself 60 real days in the past -> within the trailing-30-
        # simulated-day window -> 2/day average -> 80 / 2 = 40 days of supply.
        with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
            cur.execute("delete from live.simulation_clock")
            cur.execute(
                "insert into live.simulation_clock (id, simulation_date, status) "
                "values (1, current_date - 60, 'paused')"
            )
            cur.execute(
                "insert into live.inventory_snapshot "
                "(id, snapshot_date, product_id, warehouse_id, quantity_on_hand, "
                "quantity_allocated, source_system) "
                "values (gen_random_uuid(), current_date - 60, 'SKU-COR-001', "
                "'WH-EAST', 100, 20, 'wms')"
            )
            cur.execute(
                "insert into live.inventory_transaction "
                "(id, transaction_at, product_id, warehouse_id, transaction_type, "
                "quantity_delta, source_system) "
                "values (gen_random_uuid(), (current_date - 62)::timestamptz, "
                "'SKU-COR-001', 'WH-EAST', 'shipment', -60, 'wms')"
            )
            cur.execute(load_kpi_sql("days_of_supply"))
            rows = cur.fetchall()
            conn.rollback()
        assert rows == [("SKU-COR-001", "WH-EAST", 40.0)]

    def test_ignores_wall_clock_time_entirely(self, owner_dsn: str) -> None:
        # Same shipment as above, but stamped at real wall-clock `now()`
        # instead of relative to the (60-simulated-days-in-the-past)
        # simulation_date. If the SQL used CURRENT_DATE/now() anywhere
        # instead of simulation_date, this transaction would fall inside
        # its window and this test would see 40.0 instead of NULL.
        with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
            cur.execute("delete from live.simulation_clock")
            cur.execute(
                "insert into live.simulation_clock (id, simulation_date, status) "
                "values (1, current_date - 60, 'paused')"
            )
            cur.execute(
                "insert into live.inventory_snapshot "
                "(id, snapshot_date, product_id, warehouse_id, quantity_on_hand, "
                "quantity_allocated, source_system) "
                "values (gen_random_uuid(), current_date - 60, 'SKU-COR-001', "
                "'WH-EAST', 100, 20, 'wms')"
            )
            cur.execute(
                "insert into live.inventory_transaction "
                "(id, transaction_at, product_id, warehouse_id, transaction_type, "
                "quantity_delta, source_system) "
                "values (gen_random_uuid(), now() - interval '2 days', "
                "'SKU-COR-001', 'WH-EAST', 'shipment', -60, 'wms')"
            )
            cur.execute(load_kpi_sql("days_of_supply"))
            rows = cur.fetchall()
            conn.rollback()
        assert rows == [("SKU-COR-001", "WH-EAST", None)]

    def test_days_of_supply_is_null_when_snapshot_exists_but_no_usage(
        self, owner_dsn: str
    ) -> None:
        with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
            cur.execute("delete from live.simulation_clock")
            cur.execute(
                "insert into live.simulation_clock (id, simulation_date, status) "
                "values (1, current_date - 60, 'paused')"
            )
            cur.execute(
                "insert into live.inventory_snapshot "
                "(id, snapshot_date, product_id, warehouse_id, quantity_on_hand, "
                "quantity_allocated, source_system) "
                "values (gen_random_uuid(), current_date - 60, 'SKU-COR-001', "
                "'WH-EAST', 100, 20, 'wms')"
            )
            cur.execute(load_kpi_sql("days_of_supply"))
            rows = cur.fetchall()
            conn.rollback()
        assert rows == [("SKU-COR-001", "WH-EAST", None)]


class TestOrderCycleTimeSemanticCorrectness:
    def test_averages_days_between_order_and_delivery(self, owner_dsn: str) -> None:
        with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
            order_date = date.today() - timedelta(days=10)
            delivery_date = date.today() - timedelta(days=4)
            cur.execute(
                "insert into live.sales_order "
                "(id, so_number, customer_id, warehouse_id, order_date, "
                "requested_date, status, source_system) "
                "values (gen_random_uuid(), 'ZZTEST-SO-CYCLE-01', 'CUST-EAST-01', "
                "'WH-EAST', %s, current_date, 'shipped', 'erp') "
                "returning id",
                (order_date,),
            )
            (so_id,) = cur.fetchone()
            cur.execute(
                "insert into live.shipment "
                "(id, sales_order_id, carrier_id, warehouse_id, ship_date, "
                "promised_delivery_date, actual_delivery_date, status, source_system) "
                "values (gen_random_uuid(), %s, 'C-001', 'WH-EAST', %s, %s, %s, "
                "'delivered', 'erp')",
                (so_id, order_date, delivery_date, delivery_date),
            )
            cur.execute(load_kpi_sql("order_cycle_time"))
            (row,) = cur.fetchall()
            conn.rollback()
        assert row == (6.0,)
