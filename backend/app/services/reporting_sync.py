"""Unit 17 (MEADOWOPS-DOM-009): the Reporting layer's sync job —
transactional layer. Pure decision logic lives in
app.domain.reporting_sync, same split as app.domain.scheduled_flow /
app.services.scheduled_flow.

sync_reporting_layer(session, simulation_date, lag_days=...) is meant to
be called once per simulation day, from app.domain.scheduler._run_tick,
BEFORE evaluate_exceptions — so a lag-staleness or conflict condition this
call produces is visible to the same tick's exception evaluation, not one
tick late. Does not commit — caller-owns-the-transaction, same convention
as every other service module in this project.

Deliberately independent of app.services.exception_engine (no import
either direction): this module exposes check_lag_staleness/
check_reporting_conflict returning its own small result types, and
exception_engine.evaluate_exceptions is the one place that translates
those into its own EntityKey/Evaluation and feeds its existing private
_sync_flags — the same reconciliation helper the other three categories
already use, left untouched.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.facts import InventorySnapshot
from app.db.reporting import ReportingInventorySnapshot, ReportingSyncState
from app.domain.reporting_sync import (
    KNOWN_CONFLICT_QTY_OFFSET,
    is_lag_stale,
    pick_conflict_entity,
    target_sync_date,
)

_SYNC_STATE_ID = "default"


@dataclass(frozen=True)
class ReportingSyncResult:
    simulation_date: date
    target_sync_date: date
    last_synced_simulation_date: date | None
    rows_synced: int
    conflict_entity: tuple[str, str] | None


@dataclass(frozen=True)
class LagStalenessCheck:
    is_stale: bool
    last_synced_simulation_date: date | None
    lag_days: Decimal | None


@dataclass(frozen=True)
class ConflictCheck:
    product_id: str
    warehouse_id: str
    is_flagged: bool
    variance: Decimal


def _lock_sync_state(session: Session) -> ReportingSyncState:
    """Same singleton-row-lock convention as
    app.services.simulation_clock_ops._lock_clock — this row is the one
    contended resource this module touches, and the scheduler's own
    max_instances=1 plus this call always running inside one tick's
    transaction is what actually prevents two syncs from racing; the lock
    is defense in depth, not the only guard."""
    row = session.execute(
        select(ReportingSyncState).where(ReportingSyncState.id == _SYNC_STATE_ID).with_for_update()
    ).scalar_one_or_none()
    if row is None:
        row = ReportingSyncState(id=_SYNC_STATE_ID)
        session.add(row)
        session.flush()
    return row


def sync_reporting_layer(
    session: Session, simulation_date: date, *, lag_days: int
) -> ReportingSyncResult:
    """Copies live.inventory_snapshot into reporting.inventory_snapshot at
    a steady-state lag behind simulation_date, catching up one day at a
    time from wherever it last left off (so a gap — simulated scheduler
    downtime, PRD 9.2 — is fully backfilled once sync resumes, not just
    jumped-to).

    On the very first day any data actually gets synced, deterministically
    designates one (product_id, warehouse_id) pair
    (app.domain.reporting_sync.pick_conflict_entity) as the permanent SR-4
    conflicting-source case: that one entity's reporting row is written
    once, corrupted by a fixed offset it was never actually live's true
    value, and then never written again — every later day this function
    runs, that entity is skipped entirely while every other entity keeps
    syncing normally. The corruption is a frozen artifact of one bad sync,
    not a rule a later observer could invert; app.domain.reporting_sync's
    docstring has the full reasoning.
    """
    state = _lock_sync_state(session)
    target = target_sync_date(simulation_date, lag_days=lag_days)
    conflict_entity = (
        (state.frozen_conflict_product_id, state.frozen_conflict_warehouse_id)
        if state.frozen_conflict_product_id is not None
        else None
    )

    if state.last_synced_simulation_date is not None:
        if state.last_synced_simulation_date >= target:
            return ReportingSyncResult(
                simulation_date=simulation_date,
                target_sync_date=target,
                last_synced_simulation_date=state.last_synced_simulation_date,
                rows_synced=0,
                conflict_entity=conflict_entity,
            )
        start = state.last_synced_simulation_date + timedelta(days=1)
    else:
        # Never synced: catch up from the earliest live history available,
        # not from `target` — otherwise a first sync that lands after
        # several days of unsynced live data would silently skip straight
        # to the latest day and never backfill the gap (PRD 9.2's
        # simulated-downtime scenario applies just as much to a layer that
        # hasn't started yet as to one that stalled mid-stream).
        earliest = session.execute(select(func.min(InventorySnapshot.snapshot_date))).scalar_one()
        if earliest is None or earliest > target:
            # No live history old enough to satisfy the lag yet — nothing
            # to sync, and last_synced_simulation_date stays None rather
            # than being advanced past data that was never actually
            # examined.
            return ReportingSyncResult(
                simulation_date=simulation_date,
                target_sync_date=target,
                last_synced_simulation_date=None,
                rows_synced=0,
                conflict_entity=conflict_entity,
            )
        start = earliest

    rows_synced = 0
    day = start
    while day <= target:
        live_rows = (
            session.execute(select(InventorySnapshot).where(InventorySnapshot.snapshot_date == day))
            .scalars()
            .all()
        )

        newly_designated_this_day = False
        if conflict_entity is None and live_rows:
            conflict_entity = pick_conflict_entity(
                [(r.product_id, r.warehouse_id) for r in live_rows]
            )
            newly_designated_this_day = conflict_entity is not None
            if conflict_entity is not None:
                state.frozen_conflict_product_id, state.frozen_conflict_warehouse_id = conflict_entity

        values = []
        for row in live_rows:
            key = (row.product_id, row.warehouse_id)
            if conflict_entity is not None and key == conflict_entity:
                if not newly_designated_this_day:
                    # Frozen: this entity's one-and-only reporting row was
                    # already written on its designation day — never
                    # touched again.
                    continue
                quantity_on_hand = row.quantity_on_hand + KNOWN_CONFLICT_QTY_OFFSET
            else:
                quantity_on_hand = row.quantity_on_hand
            values.append(
                {
                    "snapshot_date": day,
                    "product_id": row.product_id,
                    "warehouse_id": row.warehouse_id,
                    "quantity_on_hand": quantity_on_hand,
                    "quantity_allocated": row.quantity_allocated,
                }
            )

        if values:
            stmt = pg_insert(ReportingInventorySnapshot).values(values).on_conflict_do_nothing()
            session.execute(stmt)
            rows_synced += len(values)

        day += timedelta(days=1)

    state.last_synced_simulation_date = target
    session.flush()

    return ReportingSyncResult(
        simulation_date=simulation_date,
        target_sync_date=target,
        last_synced_simulation_date=target,
        rows_synced=rows_synced,
        conflict_entity=conflict_entity,
    )


def check_lag_staleness(
    session: Session, simulation_date: date, *, max_lag_days: int
) -> LagStalenessCheck:
    """PRD 9.2's "lag exceeding its expected window" check — read-only,
    reads whatever sync_reporting_layer last left in reporting.sync_state
    rather than re-deriving anything itself."""
    state = session.execute(
        select(ReportingSyncState).where(ReportingSyncState.id == _SYNC_STATE_ID)
    ).scalar_one_or_none()
    last_synced = state.last_synced_simulation_date if state is not None else None
    stale = is_lag_stale(
        simulation_date=simulation_date,
        last_synced_simulation_date=last_synced,
        max_lag_days=max_lag_days,
    )
    lag_days = Decimal((simulation_date - last_synced).days) if last_synced is not None else None
    return LagStalenessCheck(is_stale=stale, last_synced_simulation_date=last_synced, lag_days=lag_days)


def check_reporting_conflict(session: Session, *, tolerance_units: Decimal) -> ConflictCheck | None:
    """Compares the seeded SR-4 conflict entity's one frozen reporting row
    against live's OWN historical record at that exact snapshot_date — not
    against today's live value, and not against live rewound to today's
    lag horizon. live.inventory_snapshot rows are never rewritten for a
    past date once written (app.services.scheduled_flow._snapshot_
    inventory_positions only ever upserts *today's* row), so this variance
    can never be explained away by waiting for the lag to catch up: it is
    exactly KNOWN_CONFLICT_QTY_OFFSET from the moment of corruption
    onward, proving the discrepancy is a genuine data-quality conflict,
    not a lag artifact.

    Returns None only when no conflict entity has been designated yet
    (the Reporting layer hasn't synced anything at all) — not itself
    "not flagged", just nothing to evaluate yet."""
    state = session.execute(
        select(ReportingSyncState).where(ReportingSyncState.id == _SYNC_STATE_ID)
    ).scalar_one_or_none()
    if state is None or state.frozen_conflict_product_id is None:
        return None
    product_id = state.frozen_conflict_product_id
    warehouse_id = state.frozen_conflict_warehouse_id

    reporting_row = session.execute(
        select(ReportingInventorySnapshot)
        .where(
            ReportingInventorySnapshot.product_id == product_id,
            ReportingInventorySnapshot.warehouse_id == warehouse_id,
        )
        .order_by(ReportingInventorySnapshot.snapshot_date.desc())
        .limit(1)
    ).scalar_one_or_none()
    if reporting_row is None:
        return None

    live_row = session.execute(
        select(InventorySnapshot).where(
            InventorySnapshot.snapshot_date == reporting_row.snapshot_date,
            InventorySnapshot.product_id == product_id,
            InventorySnapshot.warehouse_id == warehouse_id,
        )
    ).scalar_one_or_none()
    live_quantity = live_row.quantity_on_hand if live_row is not None else 0

    variance = Decimal(abs(reporting_row.quantity_on_hand - live_quantity))
    return ConflictCheck(
        product_id=product_id,
        warehouse_id=warehouse_id,
        is_flagged=variance > tolerance_units,
        variance=variance,
    )
