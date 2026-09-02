"""Unit 5 (MEADOWOPS-PROD-001): baseline data generator seeds PRD Section 3's
starter Meadow Packaging & Supply state. Real DB, real inserts, idempotency
proven by running the seeder twice.

Assertions here verify the seeder's contract — "baseline data of these
exact PRD values exists" — not which specific invocation wrote it. An
earlier version of this fixture deleted-then-reseeded this module's known
IDs before each test to prove fresher attribution; removed (advisor review
after the Unit 4 review pass, see decision correcting 1524): a hard DELETE
against canonical entity IDs like S-001/C-002 is a ForeignKeyViolation
waiting to happen the moment a later unit (Unit 13, procure-to-stock /
order-to-ship) commits a PurchaseOrder or Shipment referencing one — and
that failure can't be avoided by scoping the delete to a rolled-back
transaction, since a non-deferrable FK is checked at delete-statement time,
not at commit. Value assertions (not just presence) below are what actually
close the "a broken/no-op seeder could still pass" gap for the case that
matters — wrong or drifted data — without ever deleting committed rows a
future unit may come to depend on. The one case this suite genuinely can't
catch is `def seed_master_data(session): pass` running against a database a
prior correct run already seeded; a genuinely fresh database (first CI run,
new dev environment) still catches that on contact.
"""

import os

import psycopg
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.services.baseline_data import seed_master_data


@pytest.fixture
def session():
    # MEADOWOPS_DATABASE_URL is already in the right postgresql+psycopg://
    # form (.env, loaded by conftest.py) — code review of this unit flagged
    # hand-parsing owner_dsn (a libpq DSN, space-separated) as fragile.
    engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_seed_master_data_creates_the_three_prd_warehouses(session: Session, owner_dsn: str) -> None:
    # Containment, not exact-set equality: other units' tests (e.g. Unit 2's
    # WH-TEST fixture) share this same dev database and leave rows behind
    # (a scratch/test DB assumption noted in the Unit 2 review) — a seeder
    # promising "these rows exist" shouldn't also promise "nothing else
    # does," which wouldn't hold in a live evolving system anyway.
    seed_master_data(session)
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute("select id from live.warehouse")
        ids = {row[0] for row in cur.fetchall()}
        assert {"WH-CENTRAL", "WH-EAST", "WH-WEST"} <= ids
        # Value check, not just presence (PRD 3.2) — a no-op/broken seeder
        # can't be masked by a leftover row from a prior correct run if the
        # row's own field values are wrong.
        cur.execute(
            "select region, capacity_pallet_positions from live.warehouse where id = 'WH-CENTRAL'"
        )
        region, capacity = cur.fetchone()
    assert (region, capacity) == ("Midwest US", 6000)


def test_seed_master_data_creates_the_six_prd_suppliers(session: Session, owner_dsn: str) -> None:
    seed_master_data(session)
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute("select id from live.supplier")
        ids = {row[0] for row in cur.fetchall()}
    assert {"S-001", "S-002", "S-003", "S-004", "S-005", "S-006"} <= ids


def test_seed_master_data_creates_the_three_prd_carriers(session: Session, owner_dsn: str) -> None:
    seed_master_data(session)
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute("select id from live.carrier")
        ids = {row[0] for row in cur.fetchall()}
        assert {"C-001", "C-002", "C-003"} <= ids
        cur.execute(
            "select transit_days_min, transit_days_max, reliability_pct "
            "from live.carrier where id = 'C-001'"
        )
        transit_min, transit_max, reliability_pct = cur.fetchone()
    assert (transit_min, transit_max) == (2, 2)
    assert float(reliability_pct) == 98.0


def test_seed_master_data_creates_at_least_twenty_skus_across_three_categories(
    session: Session, owner_dsn: str
) -> None:
    seed_master_data(session)
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute("select category, count(*) from live.product group by category")
        counts = dict(cur.fetchall())
        assert sum(counts.values()) >= 20
        assert {
            "corrugated_packaging",
            "protective_packaging",
            "shipping_labeling_supplies",
        } <= set(counts.keys())
        cur.execute(
            "select category, unit_cost from live.product where id = 'SKU-COR-001'"
        )
        category, unit_cost = cur.fetchone()
    assert category == "corrugated_packaging"
    assert float(unit_cost) == 0.85


def test_seed_master_data_creates_customers_assigned_across_all_warehouses(
    session: Session, owner_dsn: str
) -> None:
    seed_master_data(session)
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute("select distinct warehouse_id from live.customer")
        warehouses = {row[0] for row in cur.fetchall()}
        assert {"WH-CENTRAL", "WH-EAST", "WH-WEST"} <= warehouses
        cur.execute(
            "select service_priority, warehouse_id from live.customer where id = 'CUST-EAST-03'"
        )
        service_priority, warehouse_id = cur.fetchone()
    assert (service_priority, warehouse_id) == ("critical", "WH-EAST")


def test_seed_master_data_is_idempotent(session: Session, owner_dsn: str) -> None:
    """Delta across a second run, not a hardcoded total — the total isn't
    this seeder's to promise on a shared table (see the previous three
    tests), but "running it twice adds nothing new" is."""
    seed_master_data(session)
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute("select count(*) from live.warehouse")
        (warehouse_count_after_first_run,) = cur.fetchone()
        cur.execute("select count(*) from live.supplier")
        (supplier_count_after_first_run,) = cur.fetchone()

    seed_master_data(session)
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute("select count(*) from live.warehouse")
        (warehouse_count_after_second_run,) = cur.fetchone()
        cur.execute("select count(*) from live.supplier")
        (supplier_count_after_second_run,) = cur.fetchone()

    assert warehouse_count_after_second_run == warehouse_count_after_first_run
    assert supplier_count_after_second_run == supplier_count_after_first_run


def test_supplier_s004_matches_the_seeded_root_cause_storyline(
    session: Session, owner_dsn: str
) -> None:
    """PRD 4.3: S-004 is the supplier whose lead time drifts in the
    canonical seeded storyline — the baseline values it starts from must be
    right (base_lead_time_days=6, not the base_lead_time_days=7 a copy-paste
    from S-001 would produce)."""
    seed_master_data(session)
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select base_lead_time_days, historical_otif_pct from live.supplier where id = 'S-004'"
        )
        base_lead_time_days, historical_otif_pct = cur.fetchone()
    assert base_lead_time_days == 6
    assert float(historical_otif_pct) == 93.0
