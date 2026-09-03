"""Unit 17 (MEADOWOPS-DOM-009): Reporting layer sync — transactional layer.
Same non-autocommit discipline as tests/services/test_scheduled_flow.py:
runs against the real seeded baseline data inside an uncommitted
transaction per test, rolled back via Session.close()'s implicit rollback.
"""

import os
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.enums import SourceSystem
from app.db.facts import InventorySnapshot
from app.db.reporting import ReportingInventorySnapshot, ReportingSyncState
from app.domain.reporting_sync import KNOWN_CONFLICT_QTY_OFFSET
from app.services.baseline_data import seed_master_data
from app.services.reporting_sync import (
    check_lag_staleness,
    check_reporting_conflict,
    sync_reporting_layer,
)

_WAREHOUSE_ID = "WH-EAST"
_PRODUCT_A = "SKU-COR-001"  # lexicographically smallest of the two seeded below
_PRODUCT_B = "SKU-COR-002"


@pytest.fixture
def session():
    engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
    with Session(engine) as session:
        seed_master_data(session)
        session.commit()
        yield session
        session.rollback()
    engine.dispose()


def _seed_live_snapshot(
    session: Session, *, snapshot_date: date, product_id: str, quantity_on_hand: int
) -> None:
    session.add(
        InventorySnapshot(
            snapshot_date=snapshot_date,
            product_id=product_id,
            warehouse_id=_WAREHOUSE_ID,
            quantity_on_hand=quantity_on_hand,
            quantity_allocated=0,
            source_system=SourceSystem.WMS,
        )
    )
    session.flush()


class TestSyncReportingLayer:
    def test_copies_live_snapshot_at_the_configured_lag(self, session: Session) -> None:
        day1 = date(2026, 3, 1)
        _seed_live_snapshot(session, snapshot_date=day1, product_id=_PRODUCT_A, quantity_on_hand=100)

        result = sync_reporting_layer(session, day1 + timedelta(days=2), lag_days=2)

        assert result.target_sync_date == day1
        row = session.execute(
            select(ReportingInventorySnapshot).where(
                ReportingInventorySnapshot.product_id == _PRODUCT_A,
                ReportingInventorySnapshot.snapshot_date == day1,
            )
        ).scalar_one()
        # SKU-COR-001/WH-EAST is the only seeded pair, so it's the
        # designated conflict entity — corrupted by the known offset.
        assert row.quantity_on_hand == 100 + KNOWN_CONFLICT_QTY_OFFSET

    def test_nothing_to_sync_yet_when_simulation_date_is_within_the_lag_window(
        self, session: Session
    ) -> None:
        day1 = date(2026, 3, 1)
        _seed_live_snapshot(session, snapshot_date=day1, product_id=_PRODUCT_A, quantity_on_hand=100)

        result = sync_reporting_layer(session, day1, lag_days=2)

        assert result.rows_synced == 0
        assert result.last_synced_simulation_date is None

    def test_catches_up_multiple_missed_days_in_one_call(self, session: Session) -> None:
        # Simulates scheduler downtime (PRD 9.2): three days of live data
        # accumulate with no sync call at all, then one call must
        # backfill every missed day, not just jump to the latest.
        #
        # Seeds two products each day: _PRODUCT_A becomes the frozen SR-4
        # conflict entity (its own behavior is covered by a dedicated
        # test below) and would only ever get one row regardless of how
        # many days are backfilled — _PRODUCT_B is the one that actually
        # proves multi-day catch-up here, since it keeps syncing normally.
        day1 = date(2026, 3, 1)
        for offset in range(3):
            for product_id in (_PRODUCT_A, _PRODUCT_B):
                _seed_live_snapshot(
                    session,
                    snapshot_date=day1 + timedelta(days=offset),
                    product_id=product_id,
                    quantity_on_hand=100 + offset,
                )

        result = sync_reporting_layer(session, day1 + timedelta(days=4), lag_days=2)

        assert result.target_sync_date == day1 + timedelta(days=2)
        synced_dates = (
            session.execute(
                select(ReportingInventorySnapshot.snapshot_date).where(
                    ReportingInventorySnapshot.product_id == _PRODUCT_B
                )
            )
            .scalars()
            .all()
        )
        assert sorted(synced_dates) == [day1, day1 + timedelta(days=1), day1 + timedelta(days=2)]

    def test_designates_the_lexicographically_smallest_pair_as_the_conflict_entity(
        self, session: Session
    ) -> None:
        day1 = date(2026, 3, 1)
        _seed_live_snapshot(session, snapshot_date=day1, product_id=_PRODUCT_B, quantity_on_hand=50)
        _seed_live_snapshot(session, snapshot_date=day1, product_id=_PRODUCT_A, quantity_on_hand=50)

        sync_reporting_layer(session, day1 + timedelta(days=2), lag_days=2)

        state = session.execute(
            select(ReportingSyncState).where(ReportingSyncState.id == "default")
        ).scalar_one()
        assert state.frozen_conflict_product_id == _PRODUCT_A
        assert state.frozen_conflict_warehouse_id == _WAREHOUSE_ID
        # The non-designated entity is copied faithfully.
        other_row = session.execute(
            select(ReportingInventorySnapshot).where(
                ReportingInventorySnapshot.product_id == _PRODUCT_B
            )
        ).scalar_one()
        assert other_row.quantity_on_hand == 50

    def test_the_conflict_entity_is_never_synced_again_after_its_designation_day(
        self, session: Session
    ) -> None:
        day1 = date(2026, 3, 1)
        _seed_live_snapshot(session, snapshot_date=day1, product_id=_PRODUCT_A, quantity_on_hand=100)
        sync_reporting_layer(session, day1 + timedelta(days=2), lag_days=2)

        # Live keeps moving for several more days...
        for offset in range(1, 5):
            _seed_live_snapshot(
                session,
                snapshot_date=day1 + timedelta(days=offset),
                product_id=_PRODUCT_A,
                quantity_on_hand=100 + offset * 10,
            )
        sync_reporting_layer(session, day1 + timedelta(days=8), lag_days=2)

        rows = (
            session.execute(
                select(ReportingInventorySnapshot).where(
                    ReportingInventorySnapshot.product_id == _PRODUCT_A
                )
            )
            .scalars()
            .all()
        )
        # Exactly one row ever exists for the frozen entity — the
        # designation-day row — no matter how many further ticks run.
        assert len(rows) == 1
        assert rows[0].snapshot_date == day1


class TestCheckLagStaleness:
    def test_not_stale_within_the_configured_window(self, session: Session) -> None:
        day1 = date(2026, 3, 1)
        _seed_live_snapshot(session, snapshot_date=day1, product_id=_PRODUCT_A, quantity_on_hand=100)
        sync_reporting_layer(session, day1 + timedelta(days=2), lag_days=2)

        check = check_lag_staleness(session, day1 + timedelta(days=2), max_lag_days=5)
        assert check.is_stale is False

    def test_never_synced_is_not_stale(self, session: Session) -> None:
        check = check_lag_staleness(session, date(2026, 3, 1), max_lag_days=5)
        assert check.is_stale is False
        assert check.last_synced_simulation_date is None

    def test_detects_staleness_after_simulated_scheduler_downtime(self, session: Session) -> None:
        # PRD 9.2: "Reporting-layer lag exceeding its expected window
        # (simulated scheduler downtime)" must be detected and surfaced.
        # Sync once, then simulate the sync job itself going down for
        # several simulation days (sync_reporting_layer simply isn't
        # called) while the simulation clock keeps advancing.
        day1 = date(2026, 3, 1)
        _seed_live_snapshot(session, snapshot_date=day1, product_id=_PRODUCT_A, quantity_on_hand=100)
        sync_reporting_layer(session, day1 + timedelta(days=2), lag_days=2)

        much_later = day1 + timedelta(days=20)
        check = check_lag_staleness(session, much_later, max_lag_days=5)
        assert check.is_stale is True
        assert check.lag_days == Decimal(20)  # much_later - day1 (last_synced_simulation_date)


class TestCheckReportingConflict:
    def test_no_conflict_entity_yet_returns_none(self, session: Session) -> None:
        assert check_reporting_conflict(session, tolerance_units=Decimal(0)) is None

    def test_flags_the_seeded_entity_with_the_known_variance(self, session: Session) -> None:
        day1 = date(2026, 3, 1)
        _seed_live_snapshot(session, snapshot_date=day1, product_id=_PRODUCT_A, quantity_on_hand=100)
        sync_reporting_layer(session, day1 + timedelta(days=2), lag_days=2)

        check = check_reporting_conflict(session, tolerance_units=Decimal(0))
        assert check is not None
        assert check.product_id == _PRODUCT_A
        assert check.is_flagged is True
        assert check.variance == Decimal(KNOWN_CONFLICT_QTY_OFFSET)

    def test_variance_is_measured_against_lives_own_historical_record_at_that_date_not_today(
        self, session: Session
    ) -> None:
        # The discriminating SR-4 property: even recomputing live's own
        # value as of the exact date the frozen reporting row claims to
        # represent, the discrepancy persists — it is not an artifact of
        # comparing against a moving "current" live figure.
        day1 = date(2026, 3, 1)
        _seed_live_snapshot(session, snapshot_date=day1, product_id=_PRODUCT_A, quantity_on_hand=100)
        sync_reporting_layer(session, day1 + timedelta(days=2), lag_days=2)

        # Live's historical row for day1 is immutable — new live activity
        # only ever adds *later* dated rows, never rewrites day1's.
        _seed_live_snapshot(
            session,
            snapshot_date=day1 + timedelta(days=10),
            product_id=_PRODUCT_A,
            quantity_on_hand=9999,
        )

        check = check_reporting_conflict(session, tolerance_units=Decimal(0))
        assert check is not None
        assert check.variance == Decimal(KNOWN_CONFLICT_QTY_OFFSET)

    def test_stays_flagged_across_many_further_ticks(self, session: Session) -> None:
        day1 = date(2026, 3, 1)
        _seed_live_snapshot(session, snapshot_date=day1, product_id=_PRODUCT_A, quantity_on_hand=100)
        sync_reporting_layer(session, day1 + timedelta(days=2), lag_days=2)

        for offset in range(1, 15):
            _seed_live_snapshot(
                session,
                snapshot_date=day1 + timedelta(days=offset),
                product_id=_PRODUCT_A,
                quantity_on_hand=100 + offset,
            )
            sync_reporting_layer(session, day1 + timedelta(days=offset + 2), lag_days=2)
            check = check_reporting_conflict(session, tolerance_units=Decimal(0))
            assert check is not None
            assert check.is_flagged is True
            assert check.variance == Decimal(KNOWN_CONFLICT_QTY_OFFSET)
