"""Unit 40 (MEADOWOPS-DOM-028): "Reset & regenerate to today".

Wipes the generated operational data - orders, purchase orders, shipments,
stock movements, transfers, snapshots, KPIs, exception flags and tick history
- and rebuilds a fresh history that ends on `today`, by running the same
daily flow the scheduler runs (flow -> reporting sync -> exceptions -> KPIs)
for each day of the window. The clock then continues from today.

What is deliberately kept: master data (products, warehouses, suppliers,
customers, carriers), users, scenarios, chat threads/messages, evaluations,
portfolio artifacts, the decision ledger and the query log. Scenarios hold
their evidence as a JSON copy, not a foreign key, so flags can be rebuilt
without orphaning them - but a live scenario's source flag no longer exists
afterwards, so every draft/approved/active scenario is cancelled (the
Builder can create fresh ones from the new flags).

Does not commit: the whole rebuild is one transaction, so a failure on any
day leaves the existing world exactly as it was, and readers keep seeing the
old data until the commit lands. It holds the simulation_clock row lock from
its first step, so a scheduler tick waits instead of interleaving.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import Base

from app.db.enums import ScenarioStatus
from app.db.exception_flags import ExceptionFlag
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
from app.db.kpi import DaysOfSupplySnapshot, KpiSnapshot
from app.db.reporting import ReportingInventorySnapshot, ReportingSyncState
from app.db.scenario import Scenario
from app.db.scheduling import PurchaseOrderLifecycleEvent, SalesOrderLifecycleEvent, ScheduledTick
from app.services.exception_engine import evaluate_exceptions
from app.services.kpi_engine import compute_and_snapshot_kpis
from app.services.reporting_sync import sync_reporting_layer
from app.services.scenario_service import cancel_scenario
from app.services.sandbox_refresh import refresh_sandbox
from app.services.scheduled_flow import run_scheduled_tick
from app.services.simulation_clock_ops import rebase_clock

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_DAYS = 45
DEFAULT_REPORTING_LAG_DAYS = 2

# Children before parents, so every delete respects the foreign keys.
GENERATED_TABLES = (
    ExceptionFlag,
    Shipment,
    SalesOrderLifecycleEvent,
    SalesOrderLine,
    SalesOrder,
    PurchaseOrderLifecycleEvent,
    PurchaseOrderLine,
    PurchaseOrder,
    WarehouseTransfer,
    InventoryTransaction,
    InventorySnapshot,
    DaysOfSupplySnapshot,
    KpiSnapshot,
    ScheduledTick,
    ReportingInventorySnapshot,
    ReportingSyncState,
)


@dataclass(frozen=True)
class RepopulateResult:
    start_date: date
    end_date: date
    days_generated: int
    scenarios_cancelled: int


def _cancel_live_scenarios(session: Session) -> int:
    live = session.scalars(
        select(Scenario).where(Scenario.status != ScenarioStatus.CANCELLED)
    ).all()
    for scenario in live:
        cancel_scenario(session, scenario.id)
    return len(live)


def repopulate_world(
    session: Session,
    *,
    today: date,
    history_days: int = DEFAULT_HISTORY_DAYS,
    reporting_lag_days: int = DEFAULT_REPORTING_LAG_DAYS,
    on_progress: Callable[[int, int], None] | None = None,
) -> RepopulateResult:
    if history_days < 1:
        raise ValueError("history_days must be at least 1")
    start_date = today - timedelta(days=history_days - 1)

    # Lock the clock first: from here until the caller commits, a scheduler
    # tick cannot advance it.
    rebase_clock(session, simulation_date=today, label=f"Repopulated to {today}")
    scenarios_cancelled = _cancel_live_scenarios(session)
    for model in GENERATED_TABLES:
        session.execute(delete(model))
    session.flush()

    for offset in range(history_days):
        day = start_date + timedelta(days=offset)
        run_scheduled_tick(session, day)
        sync_reporting_layer(session, day, lag_days=reporting_lag_days)
        evaluate_exceptions(session, day)
        compute_and_snapshot_kpis(session, day)
        if on_progress is not None:
            on_progress(offset + 1, history_days)

    return RepopulateResult(
        start_date=start_date,
        end_date=today,
        days_generated=history_days,
        scenarios_cancelled=scenarios_cancelled,
    )


def build_repopulate_work(
    engine: Engine, settings: Settings, *, today: date, history_days: int
) -> Callable[[Callable[[int, int], None]], str]:
    """The unit of work app.services.repopulate_job runs on its worker
    thread: the whole rebuild in one session/transaction, then a sandbox
    refresh so the Analyst's query sandbox mirrors the new world too. A
    refresh failure does not undo the rebuild (it is already committed) - it
    is reported in the outcome message instead."""

    def work(on_progress: Callable[[int, int], None]) -> str:
        with Session(engine) as session:
            result = repopulate_world(
                session,
                today=today,
                history_days=history_days,
                reporting_lag_days=settings.reporting_lag_days,
                on_progress=on_progress,
            )
            session.commit()
        summary = (
            f"Rebuilt {result.days_generated} days of history ending {result.end_date}. "
            f"{result.scenarios_cancelled} scenario(s) cancelled."
        )
        refresh = refresh_sandbox(settings.owner_dsn(), Base.metadata)
        if refresh.error is not None:
            logger.error("Sandbox refresh after repopulate failed: %s", refresh.error)
            return f"{summary} The sandbox refresh failed - use Refresh sandbox to retry."
        return f"{summary} Sandbox refreshed."

    return work
