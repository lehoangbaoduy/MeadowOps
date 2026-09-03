"""Unit 14 (MEADOWOPS-DOMAIN-006): KPI engine — executes Unit 10's starter
KPI SQL against the real `live` schema and persists a snapshot stamped with
simulation_date (kpi_snapshot / days_of_supply_snapshot), so Unit 16's
dashboard drill-down endpoints have real history to read instead of
recomputing on every request.

Security review of this unit: the four scalar KPIs (otif/fill_rate/
order_cycle_time/perfect_order_rate) are all-time aggregates with no date
filter — days_of_supply.sql's own "latest snapshot" CTE is similarly
unbounded — none of Unit 10's SQL files compute a value "as of" a specific
historical simulation_date, only "as of right now." So a kpi_snapshot row
is accurately described as "the all-time cumulative KPI value, recorded on
this date" — NOT a true point-in-time historical figure. Calling this
function is only meaningful in step with the clock moving forward (as
Unit 13's scheduler does); see compute_and_snapshot_kpis's own docstring
for the guard against the unsafe "recompute an earlier day after later
data already exists" pattern, which would otherwise silently overwrite a
correct row with a wrong one.

This module doesn't change what the SQL means — every value is still a
Builder-set placeholder pending Analyst review (PRD line 207); see
sql/kpi/*.sql's own docstrings for each metric's stated simplifying
assumptions. It runs that SQL and stores the result.

Does not commit — same caller-owns-the-transaction convention as
simulation_clock_ops/scheduled_flow.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.kpi import DaysOfSupplySnapshot, KpiSnapshot
from app.domain.kpi_sql import load_kpi_sql

DaysOfSupplyRow = tuple[str, str, Decimal | None]


class KpiComputationOutOfOrderError(RuntimeError):
    """Raised when asked to (re)compute a simulation_date earlier than the
    latest date already snapshotted — since every KPI query here is an
    all-time aggregate, not date-bounded, computing an earlier day after a
    later one has already run would silently overwrite that earlier day's
    correct row with today's (wrong, too-recent) numbers. Loud failure
    instead of quiet data corruption."""


@dataclass(frozen=True)
class KpiComputationResult:
    simulation_date: date
    otif_pct: Decimal | None
    fill_rate_pct: Decimal | None
    order_cycle_time_days: Decimal | None
    perfect_order_rate_pct: Decimal | None
    days_of_supply: list[DaysOfSupplyRow]  # (product_id, warehouse_id, value)


def _run_scalar(session: Session, kpi_name: str) -> Decimal | None:
    return session.execute(text(load_kpi_sql(kpi_name))).scalar_one()


def _run_days_of_supply(session: Session) -> list[DaysOfSupplyRow]:
    rows = session.execute(text(load_kpi_sql("days_of_supply"))).all()
    return [(r.product_id, r.warehouse_id, r.days_of_supply) for r in rows]


def _upsert_kpi_snapshot(
    session: Session,
    simulation_date: date,
    otif_pct: Decimal | None,
    fill_rate_pct: Decimal | None,
    order_cycle_time_days: Decimal | None,
    perfect_order_rate_pct: Decimal | None,
) -> None:
    stmt = pg_insert(KpiSnapshot).values(
        simulation_date=simulation_date,
        otif_pct=otif_pct,
        fill_rate_pct=fill_rate_pct,
        order_cycle_time_days=order_cycle_time_days,
        perfect_order_rate_pct=perfect_order_rate_pct,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["simulation_date"],
        set_={
            "otif_pct": stmt.excluded.otif_pct,
            "fill_rate_pct": stmt.excluded.fill_rate_pct,
            "order_cycle_time_days": stmt.excluded.order_cycle_time_days,
            "perfect_order_rate_pct": stmt.excluded.perfect_order_rate_pct,
            "computed_at": func.now(),
        },
    )
    session.execute(stmt)


def _upsert_days_of_supply_snapshots(
    session: Session, simulation_date: date, rows: list[DaysOfSupplyRow]
) -> None:
    if not rows:
        return
    values = [
        {
            "simulation_date": simulation_date,
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "days_of_supply": value,
        }
        for product_id, warehouse_id, value in rows
    ]
    stmt = pg_insert(DaysOfSupplySnapshot).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["simulation_date", "product_id", "warehouse_id"],
        set_={
            "days_of_supply": stmt.excluded.days_of_supply,
            "computed_at": func.now(),
        },
    )
    session.execute(stmt)


def compute_and_snapshot_kpis(session: Session, simulation_date: date) -> KpiComputationResult:
    """Idempotent for the SAME simulation_date: re-running it replaces
    (ON CONFLICT DO UPDATE) rather than accumulating duplicate snapshot
    rows — e.g. after the scheduler's own tick failed and retried the same
    day. Raises KpiComputationOutOfOrderError for an EARLIER date than the
    latest one already snapshotted (security review of this unit): every
    KPI query here is an all-time aggregate, not bounded to
    simulation_date, so recomputing an earlier day after later data
    already exists would silently overwrite that earlier day's correct
    row with today's (too-recent, wrong) numbers — a real, previously
    undetected correctness gap this guard converts into a loud failure."""
    latest = session.execute(select(func.max(KpiSnapshot.simulation_date))).scalar_one()
    if latest is not None and simulation_date < latest:
        raise KpiComputationOutOfOrderError(
            f"cannot compute KPIs for {simulation_date} — a later date ({latest}) is "
            "already snapshotted, and every KPI here is an all-time aggregate, not a "
            "point-in-time figure for the requested date"
        )
    otif = _run_scalar(session, "otif")
    fill_rate = _run_scalar(session, "fill_rate")
    order_cycle_time = _run_scalar(session, "order_cycle_time")
    perfect_order_rate = _run_scalar(session, "perfect_order_rate")
    days_of_supply = _run_days_of_supply(session)

    _upsert_kpi_snapshot(
        session, simulation_date, otif, fill_rate, order_cycle_time, perfect_order_rate
    )
    _upsert_days_of_supply_snapshots(session, simulation_date, days_of_supply)
    session.flush()

    return KpiComputationResult(
        simulation_date=simulation_date,
        otif_pct=otif,
        fill_rate_pct=fill_rate,
        order_cycle_time_days=order_cycle_time,
        perfect_order_rate_pct=perfect_order_rate,
        days_of_supply=days_of_supply,
    )
