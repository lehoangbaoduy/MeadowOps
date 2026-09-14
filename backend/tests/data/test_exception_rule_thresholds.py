"""Tests for the default exception-rule thresholds table (PRD S1-FR-4/
S1-FR-10, spec MEADOWOPS-DOMAIN-004).

Runtime-mutable, unlike the KPI SQL: PRD line 627 maps exception-threshold
config to the admin Settings page, and S1-FR-4/S1-FR-10 both say thresholds
are Analyst-adjustable once Active Use begins - so this needs a table an
admin CRUD surface can read/write (Unit 15's exception engine reads it;
whichever later unit wires Settings CRUD for it writes it), not a Python
constant or a file. Builder-set defaults for Build & Test (PRD line 207),
not treated as final.
"""

import psycopg
import pytest

from app.services.exception_rule_defaults import EXCEPTION_RULE_THRESHOLDS

EXPECTED_IDS = {
    "low_stock_days_of_supply",
    "at_risk_po_grace_days",
    "late_shipment_grace_days",
    # Unit 17 (MEADOWOPS-DOM-009, SR-2/SR-4): the Reporting layer's own
    # two threshold-driven categories.
    "reporting_lag_stale",
    "reporting_conflict_qty_variance",
    # Unit 30 (MEADOWOPS-DOM-030, PRD 9.2 catalog row 2 / SR-3).
    "duplicate_purchase_order",
}


def test_exception_rule_threshold_table_exists(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select column_name from information_schema.columns "
            "where table_schema = 'live' and table_name = 'exception_rule_threshold'"
        )
        columns = {row[0] for row in cur.fetchall()}
    assert {"id", "name", "description", "threshold_value", "unit", "is_active"} <= columns


def test_default_definitions_cover_the_five_named_exception_types() -> None:
    # Matches Unit 15's engine (at-risk PO / low stock / late shipment)
    # plus Unit 17's Reporting-layer categories (lag-stale / conflict-qty-
    # variance) exactly - the defaults seeder defines precisely the
    # categories those two engines' calls evaluate, no more and no less.
    ids = {row["id"] for row in EXCEPTION_RULE_THRESHOLDS}
    assert ids == EXPECTED_IDS


def test_default_threshold_values_are_seeded_and_non_negative(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select id, threshold_value, unit, is_active "
            "from live.exception_rule_threshold order by id"
        )
        rows = {row[0]: row[1:] for row in cur.fetchall()}
    assert set(rows) == EXPECTED_IDS
    for threshold_value, unit, is_active in rows.values():
        assert threshold_value >= 0
        assert unit in ("days", "units", "count")
        assert is_active is True


def test_low_stock_threshold_is_grounded_in_the_slowest_seeded_supplier_lead_time(
    owner_dsn: str,
) -> None:
    # DD-15: the default isn't an arbitrary round number - it's derived from
    # the actual seeded supplier lead times (5-12 days), so a warehouse
    # running below its slowest supplier's replenishment time gets flagged
    # before it actually runs out.
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute("select max(base_lead_time_days) from live.supplier")
        (max_lead_time,) = cur.fetchone()
        cur.execute(
            "select threshold_value from live.exception_rule_threshold "
            "where id = 'low_stock_days_of_supply'"
        )
        (threshold,) = cur.fetchone()
    assert threshold >= max_lead_time


def test_seeding_default_thresholds_is_idempotent(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute("select count(*) from live.exception_rule_threshold")
        (count_before,) = cur.fetchone()
    # seed_exception_rule_thresholds itself is exercised for real by
    # e2e/scripts/start-backend.sh and backend-ci.yml's own bootstrap seed
    # step (not here, to avoid a second DB session/engine in a
    # psycopg-only test file) - this test instead re-runs the same ON
    # CONFLICT DO NOTHING insert directly and asserts the row count
    # doesn't change on a second pass, proving the idempotency the seeder
    # module documents.
    with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
        for row in EXCEPTION_RULE_THRESHOLDS:
            cur.execute(
                "insert into live.exception_rule_threshold "
                "(id, name, description, threshold_value, unit, is_active) "
                "values (%(id)s, %(name)s, %(description)s, %(threshold_value)s, "
                "%(unit)s, %(is_active)s) on conflict (id) do nothing",
                row,
            )
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute("select count(*) from live.exception_rule_threshold")
        (count_after,) = cur.fetchone()
    assert count_after == count_before


def test_negative_threshold_value_is_rejected(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "insert into live.exception_rule_threshold "
                "(id, name, description, threshold_value, unit, is_active) "
                "values ('ZZTEST-negative-rule', 'x', 'x', -1, 'days', true)"
            )
        conn.rollback()
