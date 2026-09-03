"""Unit 14 (MEADOWOPS-DOMAIN-006): KPI engine — executes Unit 10's starter
KPI SQL and persists a snapshot. Scenarios here are built directly (not via
Unit 13's seeded-random flow) so the expected KPI values are exact and
deterministic, not dependent on which day a shipment happens to deliver on.
"""

import os
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.enums import SalesOrderStatus, ShipmentStatus, SourceSystem
from app.db.facts import SalesOrder, SalesOrderLine, Shipment
from app.db.kpi import DaysOfSupplySnapshot, KpiSnapshot
from app.services.baseline_data import seed_master_data
from app.services.kpi_engine import KpiComputationOutOfOrderError, compute_and_snapshot_kpis
from app.services.scheduled_flow import _snapshot_inventory_positions

SIM_DATE = date(2026, 3, 2)
_PRODUCT_ID = "SKU-COR-001"
_WAREHOUSE_ID = "WH-EAST"
_CUSTOMER_ID = "CUST-EAST-01"


@pytest.fixture
def session():
    engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
    with Session(engine) as session:
        seed_master_data(session)
        session.commit()
        yield session
        session.rollback()
    engine.dispose()


def _delivered_order(
    session: Session,
    *,
    order_date: date,
    quantity_ordered: int,
    quantity_shipped: int,
    on_time: bool,
) -> None:
    so = SalesOrder(
        so_number=f"SO-TEST-{uuid.uuid4().hex[:8]}",
        customer_id=_CUSTOMER_ID,
        warehouse_id=_WAREHOUSE_ID,
        order_date=order_date,
        requested_date=order_date + timedelta(days=3),
        status=SalesOrderStatus.SHIPPED,
        source_system=SourceSystem.ERP,
    )
    session.add(so)
    session.flush()
    session.add(
        SalesOrderLine(
            sales_order_id=so.id,
            product_id=_PRODUCT_ID,
            quantity_ordered=quantity_ordered,
            quantity_shipped=quantity_shipped,
            unit_price=1.0,
        )
    )
    ship_date = order_date + timedelta(days=1)
    promised = ship_date + timedelta(days=2)
    actual = promised if on_time else promised + timedelta(days=3)
    session.add(
        Shipment(
            sales_order_id=so.id,
            carrier_id="C-001",
            warehouse_id=_WAREHOUSE_ID,
            ship_date=ship_date,
            promised_delivery_date=promised,
            actual_delivery_date=actual,
            status=ShipmentStatus.DELIVERED,
            source_system=SourceSystem.WMS,
        )
    )
    session.flush()


class TestComputeAndSnapshotKpis:
    def test_no_data_yields_all_none_scalars_and_no_days_of_supply_rows(
        self, session: Session
    ) -> None:
        result = compute_and_snapshot_kpis(session, SIM_DATE)
        assert result.otif_pct is None
        assert result.fill_rate_pct is None
        assert result.order_cycle_time_days is None
        assert result.perfect_order_rate_pct is None
        assert result.days_of_supply == []

    def test_persists_a_kpi_snapshot_row_for_the_simulation_date(self, session: Session) -> None:
        compute_and_snapshot_kpis(session, SIM_DATE)
        row = session.execute(
            select(KpiSnapshot).where(KpiSnapshot.simulation_date == SIM_DATE)
        ).scalar_one()
        assert row is not None

    def test_rerunning_the_same_date_upserts_rather_than_duplicates(
        self, session: Session
    ) -> None:
        compute_and_snapshot_kpis(session, SIM_DATE)
        compute_and_snapshot_kpis(session, SIM_DATE)
        rows = session.execute(
            select(KpiSnapshot).where(KpiSnapshot.simulation_date == SIM_DATE)
        ).scalars().all()
        assert len(rows) == 1

    def test_computing_a_later_date_after_an_earlier_one_succeeds(self, session: Session) -> None:
        compute_and_snapshot_kpis(session, SIM_DATE)
        compute_and_snapshot_kpis(session, SIM_DATE + timedelta(days=1))  # must not raise
        rows = session.execute(select(KpiSnapshot)).scalars().all()
        assert len(rows) == 2

    def test_computing_an_earlier_date_after_a_later_one_raises(self, session: Session) -> None:
        compute_and_snapshot_kpis(session, SIM_DATE)
        with pytest.raises(KpiComputationOutOfOrderError):
            compute_and_snapshot_kpis(session, SIM_DATE - timedelta(days=1))

    def test_out_of_order_call_does_not_overwrite_the_existing_later_row(
        self, session: Session
    ) -> None:
        _delivered_order(
            session, order_date=SIM_DATE, quantity_ordered=10, quantity_shipped=10, on_time=True
        )
        compute_and_snapshot_kpis(session, SIM_DATE)  # otif_pct == 100, see below
        with pytest.raises(KpiComputationOutOfOrderError):
            compute_and_snapshot_kpis(session, SIM_DATE - timedelta(days=1))
        row = session.execute(
            select(KpiSnapshot).where(KpiSnapshot.simulation_date == SIM_DATE)
        ).scalar_one()
        assert row.otif_pct == 100  # untouched by the rejected out-of-order call

    def test_a_fully_shipped_on_time_order_yields_100_pct_otif(self, session: Session) -> None:
        _delivered_order(
            session, order_date=SIM_DATE, quantity_ordered=10, quantity_shipped=10, on_time=True
        )
        result = compute_and_snapshot_kpis(session, SIM_DATE)
        assert result.otif_pct == 100

    def test_a_late_delivery_excludes_the_order_from_otif(self, session: Session) -> None:
        _delivered_order(
            session, order_date=SIM_DATE, quantity_ordered=10, quantity_shipped=10, on_time=False
        )
        result = compute_and_snapshot_kpis(session, SIM_DATE)
        assert result.otif_pct == 0

    def test_fill_rate_reflects_shipped_over_ordered_quantity(self, session: Session) -> None:
        _delivered_order(
            session, order_date=SIM_DATE, quantity_ordered=20, quantity_shipped=10, on_time=True
        )
        result = compute_and_snapshot_kpis(session, SIM_DATE)
        assert result.fill_rate_pct == 50

    def test_order_cycle_time_is_days_from_order_to_delivery(self, session: Session) -> None:
        # order_date=SIM_DATE, ship_date=+1, promised=+3, delivered on time -> actual=+3
        _delivered_order(
            session, order_date=SIM_DATE, quantity_ordered=10, quantity_shipped=10, on_time=True
        )
        result = compute_and_snapshot_kpis(session, SIM_DATE)
        assert result.order_cycle_time_days == 3

    def test_days_of_supply_reflects_the_inventory_snapshot_just_written(
        self, session: Session
    ) -> None:
        _snapshot_inventory_positions(session, SIM_DATE)
        result = compute_and_snapshot_kpis(session, SIM_DATE)
        keys = {(p, w) for p, w, _ in result.days_of_supply}
        assert (_PRODUCT_ID, _WAREHOUSE_ID) in keys
        assert len(result.days_of_supply) > 0

    def test_days_of_supply_snapshot_rows_persisted_and_upserted(self, session: Session) -> None:
        _snapshot_inventory_positions(session, SIM_DATE)
        compute_and_snapshot_kpis(session, SIM_DATE)
        compute_and_snapshot_kpis(session, SIM_DATE)  # re-run same day
        rows = session.execute(
            select(DaysOfSupplySnapshot).where(
                DaysOfSupplySnapshot.simulation_date == SIM_DATE,
                DaysOfSupplySnapshot.product_id == _PRODUCT_ID,
                DaysOfSupplySnapshot.warehouse_id == _WAREHOUSE_ID,
            )
        ).scalars().all()
        assert len(rows) == 1  # upserted, not duplicated
