"""Unit 13 (MEADOWOPS-DOM-006): APScheduler wiring for the scheduled
procure-to-stock/order-to-ship flow. One BackgroundScheduler job per app
instance, each tick: advance the simulation clock one day, then run the
flow for that new date — entirely inside its own short-lived
session/transaction, independent of any request-scoped session (DD-11,
same convention as app.db.session.get_session).

Gated by settings.scheduler_enabled (default False, app/core/config.py) so
tests/CI never get a background thread they didn't ask for.

Unit 16: also runs Unit 15's exception evaluation and Unit 14's KPI
snapshot for the new simulation_date, right after the flow itself. Before
this, neither function had any caller anywhere in the running system (B9)
— exception_flag and kpi_snapshot/days_of_supply_snapshot stayed empty
even with the scheduler enabled, so the dashboard (Unit 16) had nothing
real to read or drill into. Both run inside the same try as
run_scheduled_tick: if the flow itself fails, evaluating exceptions or
snapshotting KPIs against a half-run tick would be evaluating a
still-moving target, so both are skipped for that tick — the next
successful tick re-evaluates exceptions fresh regardless (idempotent,
app.services.exception_engine) and simply produces one fewer day of KPI
history (already-accepted, app.services.kpi_engine's own "recorded-on, not
point-in-time" semantics).
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.services.exception_engine import evaluate_exceptions
from app.services.kpi_engine import compute_and_snapshot_kpis
from app.services.reporting_sync import sync_reporting_layer
from app.services.scheduled_flow import run_scheduled_tick
from app.services.simulation_clock_ops import SimulationPausedError, advance_simulation

logger = logging.getLogger(__name__)

JOB_ID = "scheduled_flow_tick"


def _run_tick(engine: Engine, reporting_lag_days: int = 2) -> None:
    """Never lets one bad tick kill the scheduler thread — APScheduler
    would otherwise just log-and-continue on an uncaught exception anyway
    (its own default), so catching explicitly here is about producing a
    clear, attributable log line, not about hiding the failure.

    Commits even on failure, not just on success — for a pure-Python
    exception, at least: run_scheduled_tick's own FAILED ScheduledTick row
    (and any already-flushed partial progress from before the exception,
    e.g. a PO that got received before a later step blew up) are real,
    already-happened facts worth keeping, and the next tick simply
    re-evaluates whatever's still open regardless. A genuine DB-level
    error is different — it has already aborted the transaction by the
    time it reaches this handler, so there is no partial progress left to
    preserve either way, and committing directly on top of that state
    would only raise PendingRollbackError; see the rollback() guard below.
    """
    with Session(engine) as session:
        try:
            new_date = advance_simulation(session)
        except SimulationPausedError:
            session.rollback()
            return
        try:
            run_scheduled_tick(session, new_date)
            # Unit 17 (MEADOWOPS-DOM-009): before evaluate_exceptions, not
            # after — a lag-staleness/conflict condition this call
            # produces must be visible to the same tick's exception
            # evaluation, not one tick late. Any exception here propagates
            # to the same except-and-still-commit handling as the other
            # three calls (logged loudly via logger.exception below, not
            # silently masked — PRD 9.2's own concern about staleness
            # applies just as much to the sync call itself failing).
            sync_reporting_layer(session, new_date, lag_days=reporting_lag_days)
            evaluate_exceptions(session, new_date)
            compute_and_snapshot_kpis(session, new_date)
        except Exception:
            logger.exception("scheduled tick failed for simulation_date=%s", new_date)
            if not session.is_active:
                # A genuine DB-level error (as opposed to a pure-Python
                # exception) leaves the session's transaction in a
                # "partial rollback" state (code review, MEDIUM) — a
                # plain commit() on top of that raises
                # PendingRollbackError, masking the original failure and
                # escaping this handler entirely. rollback() first clears
                # that state, the same trap
                # app.services.scheduled_flow.run_scheduled_tick's own
                # recovery write already guards against. A pure-Python
                # exception never dirties the session's transactional
                # state (session.is_active stays True), so it skips this
                # branch and the fallback commit below still preserves
                # whatever partial progress had already been flushed —
                # unchanged from before this guard was added.
                session.rollback()
        session.commit()


def build_scheduler(
    engine: Engine, *, interval_seconds: int, reporting_lag_days: int = 2
) -> BackgroundScheduler:
    # max_instances=1 only prevents overlapping ticks within THIS process
    # (security review, LOW) — if ever deployed with multiple app
    # workers/replicas, each would run its own scheduler against the same
    # database, advancing the sim clock N times per interval. No worker/
    # replica config exists yet (8.2's deployment target is still an open
    # blocker, B1), so this isn't live today; revisit when that's decided —
    # a single-worker deployment, or a leader-election guard, or moving the
    # tick to an external cron hitting a dedicated endpoint.
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _run_tick,
        "interval",
        seconds=interval_seconds,
        args=[engine, reporting_lag_days],
        id=JOB_ID,
        max_instances=1,  # never let two ticks overlap and race the clock lock
        coalesce=True,
    )
    return scheduler
