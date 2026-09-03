"""Unit 15 (MEADOWOPS-DOM-008): exception engine — the transactional layer.
Pure decision logic lives in app.domain.exception_engine, same split as
app.domain.scheduled_flow / app.services.scheduled_flow.

Reads thresholds fresh from live.exception_rule_threshold (Unit 10) on
every call, never caches them — S1-FR-10 makes them Analyst-adjustable at
runtime. Reads days-of-supply by running sql/kpi/days_of_supply.sql
directly (the same way app.services.kpi_engine does), not from
days_of_supply_snapshot: that snapshot table has no populated history yet
(see B9 in the progress doc — its own would-be caller, the scheduler tick,
never invokes it), and even once it is wired in, a flagging decision wants
the current value, not a "recorded-on" figure that could be a day stale.

evaluate_exceptions(session, simulation_date) is meant to be called once
per simulation day. Idempotent per day and safe to call repeatedly:
re-running with nothing changed neither duplicates open flags nor
resolves ones that are still genuinely open (see _sync_flags). Does not
commit — caller-owns-the-transaction, same convention as every other
service module in this project.

Acquires a Postgres advisory transaction lock as its first action
(security review): _sync_flags reads existing open flags, decides in
Python, then writes — a read-then-decide-then-write sequence with no
row to pin the way _lock_clock's SELECT ... FOR UPDATE does (there's no
singleton row here). Two overlapping calls without a lock could both
decide "no open flag for entity X" and both insert one; the partial
unique index (migration 0012) would catch the resulting duplicate as an
IntegrityError, but that would abort the *whole* call, including
already-staged updates for the other two categories, in the same
transaction. pg_advisory_xact_lock auto-releases at transaction end, so
nothing here needs to explicitly unlock. Not exploitable today — nothing
calls this function concurrently yet, and it isn't wired into the
scheduler (B9) — but cheap to close now rather than inherit silently
once a later unit does wire it in.

Design choice, stated explicitly: an inactive threshold (is_active=False)
is skipped entirely for that call — no new flags are opened for it, but
any of its already-open flags are left untouched rather than resolved,
since deactivating a rule isn't evidence the underlying condition cleared.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.enums import ShipmentStatus
from app.db.exception_flags import ExceptionFlag
from app.db.exception_rules import ExceptionRuleThreshold
from app.db.facts import PurchaseOrder, Shipment
from app.domain.exception_engine import (
    evaluate_at_risk_purchase_order,
    evaluate_late_shipment,
    evaluate_low_stock,
)
from app.domain.kpi_sql import load_kpi_sql
from app.services.reporting_sync import check_lag_staleness, check_reporting_conflict

# Must match app.services.exception_rule_defaults.EXCEPTION_RULE_THRESHOLDS'
# ids exactly — that seeder is the single source of truth for these three
# rule identities.
LOW_STOCK_CATEGORY = "low_stock_days_of_supply"
AT_RISK_PO_CATEGORY = "at_risk_po_grace_days"
LATE_SHIPMENT_CATEGORY = "late_shipment_grace_days"
# Unit 17 (MEADOWOPS-DOM-009, SR-2/SR-4): deliberately independent of
# app.services.reporting_sync's own EntityKey-shaped internals — that
# module returns its own small check types, translated into this
# module's EntityKey/Evaluation right here, so the two modules don't
# import each other's private machinery in both directions.
REPORTING_LAG_STALE_CATEGORY = "reporting_lag_stale"
REPORTING_CONFLICT_CATEGORY = "reporting_conflict_qty_variance"

# Arbitrary fixed key for the advisory lock, unique to this module — any
# constant works, since pg_advisory_xact_lock's keyspace is just a shared
# integer namespace two callers need to agree on to actually serialize.
_ADVISORY_LOCK_KEY = "meadowops:exception_engine:evaluate_exceptions"


class EntityKey(NamedTuple):
    product_id: str | None = None
    warehouse_id: str | None = None
    purchase_order_id: uuid.UUID | None = None
    shipment_id: uuid.UUID | None = None


# is_flagged is a tri-state, not a plain bool (security review, HIGH):
# True/False are confident verdicts; None means "inconclusive this call" —
# e.g. days_of_supply came back NULL because there's no shipment activity
# in the trailing window, or the simulation clock isn't seeded yet. An
# inconclusive verdict must neither open a new flag nor resolve an
# existing one — "we couldn't measure it this tick" is not evidence the
# condition cleared.
class Evaluation(NamedTuple):
    is_flagged: bool | None
    measured_value: Decimal | None


@dataclass(frozen=True)
class ExceptionEvaluationResult:
    simulation_date: date
    opened: int
    resolved: int
    still_open: int


def _load_active_thresholds(session: Session) -> dict[str, ExceptionRuleThreshold]:
    rows = session.execute(
        select(ExceptionRuleThreshold).where(ExceptionRuleThreshold.is_active.is_(True))
    ).scalars()
    return {row.id: row for row in rows}


def _grace_days(threshold_value: Decimal) -> int:
    # Rounded, not truncated (security review, LOW): threshold_value is a
    # Numeric(10, 2) column, so an Analyst-set fractional grace period
    # (e.g. 2.7 days via the future Settings UI, S1-FR-10) is a deliberate
    # rounding decision, not a silent floor via int().
    return int(round(threshold_value))


def _sync_flags(
    session: Session,
    *,
    category: str,
    simulation_date: date,
    threshold_value: Decimal,
    evaluations: dict[EntityKey, Evaluation],
) -> tuple[int, int]:
    """Reconciles `evaluations` (every entity this call actually looked at,
    its verdict, and its measured value) against the category's existing
    open flags.

    An entity omitted from `evaluations` entirely is treated like one
    present-but-confidently-not-flagged — both auto-resolve any open flag
    — so callers are free to narrow their query to only the entities that
    could plausibly still be open (e.g. non-terminal purchase orders)
    without breaking auto-resolution for one that just closed out. An
    entity present with an inconclusive (None) verdict is left untouched:
    neither resolved nor opened (see Evaluation's docstring).

    threshold_value is only ever written on INSERT, never on UPDATE
    (security review, MEDIUM) — an already-open flag's threshold_value is
    frozen at whatever was in effect when it was first detected, so a
    later Analyst threshold change (S1-FR-10) can't retroactively rewrite
    what actually triggered it. measured_value and simulation_date (the
    last-observed date) do update on every sync, since those describe the
    entity's current state, not the detection event."""
    existing = {
        EntityKey(row.product_id, row.warehouse_id, row.purchase_order_id, row.shipment_id): row
        for row in session.execute(
            select(ExceptionFlag).where(
                ExceptionFlag.category == category, ExceptionFlag.resolved_at.is_(None)
            )
        ).scalars()
    }

    resolved_keys: set[EntityKey] = set()
    for key, row in existing.items():
        is_flagged, _ = evaluations.get(key, Evaluation(False, None))
        if is_flagged is None:
            continue
        if not is_flagged:
            row.resolved_at = func.now()
            resolved_keys.add(key)

    opened = 0
    for key, (is_flagged, measured_value) in evaluations.items():
        if not is_flagged:  # covers both False and None (inconclusive)
            continue
        if key in existing and key not in resolved_keys:
            row = existing[key]
            row.measured_value = measured_value
            row.simulation_date = simulation_date
        else:
            session.add(
                ExceptionFlag(
                    category=category,
                    product_id=key.product_id,
                    warehouse_id=key.warehouse_id,
                    purchase_order_id=key.purchase_order_id,
                    shipment_id=key.shipment_id,
                    simulation_date=simulation_date,
                    first_detected_simulation_date=simulation_date,
                    measured_value=measured_value,
                    threshold_value=threshold_value,
                )
            )
            opened += 1

    return opened, len(resolved_keys)


def _current_days_of_supply(session: Session) -> dict[EntityKey, Decimal | None]:
    rows = session.execute(text(load_kpi_sql("days_of_supply"))).all()
    return {
        EntityKey(product_id=r.product_id, warehouse_id=r.warehouse_id): r.days_of_supply
        for r in rows
    }


def _at_risk_po_evaluations(
    session: Session, simulation_date: date, grace_days: int
) -> dict[EntityKey, Evaluation]:
    rows = session.execute(
        select(PurchaseOrder.id, PurchaseOrder.expected_delivery_date, PurchaseOrder.status)
    ).all()
    evaluations: dict[EntityKey, Evaluation] = {}
    for r in rows:
        flagged = evaluate_at_risk_purchase_order(
            expected_delivery_date=r.expected_delivery_date,
            simulation_date=simulation_date,
            grace_days=grace_days,
            status=r.status,
        )
        days_past_due = Decimal((simulation_date - r.expected_delivery_date).days)
        evaluations[EntityKey(purchase_order_id=r.id)] = Evaluation(flagged, days_past_due)
    return evaluations


def _late_shipment_evaluations(
    session: Session, simulation_date: date, grace_days: int
) -> dict[EntityKey, Evaluation]:
    rows = session.execute(
        select(
            Shipment.id,
            Shipment.promised_delivery_date,
            Shipment.actual_delivery_date,
            Shipment.status,
        )
    ).all()
    evaluations: dict[EntityKey, Evaluation] = {}
    for r in rows:
        flagged = evaluate_late_shipment(
            promised_delivery_date=r.promised_delivery_date,
            actual_delivery_date=r.actual_delivery_date,
            simulation_date=simulation_date,
            grace_days=grace_days,
            status=r.status,
        )
        # Mirrors evaluate_late_shipment's own status check exactly
        # (security review, LOW): actual_delivery_date only means anything
        # once the shipment is truly DELIVERED — a row with
        # actual_delivery_date set but a different status (a data anomaly
        # nothing in the schema prevents) must still be measured against
        # simulation_date, the same reference the flagging decision used.
        if r.status == ShipmentStatus.DELIVERED and r.actual_delivery_date is not None:
            reference_date = r.actual_delivery_date
        else:
            reference_date = simulation_date
        days_late = Decimal((reference_date - r.promised_delivery_date).days)
        evaluations[EntityKey(shipment_id=r.id)] = Evaluation(flagged, days_late)
    return evaluations


def evaluate_exceptions(session: Session, simulation_date: date) -> ExceptionEvaluationResult:
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": _ADVISORY_LOCK_KEY})

    thresholds = _load_active_thresholds(session)
    opened = resolved = 0

    if LOW_STOCK_CATEGORY in thresholds:
        threshold = thresholds[LOW_STOCK_CATEGORY]
        evaluations = {
            key: Evaluation(
                evaluate_low_stock(value, threshold_days=threshold.threshold_value)
                if value is not None
                else None,
                value,
            )
            for key, value in _current_days_of_supply(session).items()
        }
        o, r = _sync_flags(
            session,
            category=LOW_STOCK_CATEGORY,
            simulation_date=simulation_date,
            threshold_value=threshold.threshold_value,
            evaluations=evaluations,
        )
        opened += o
        resolved += r

    if AT_RISK_PO_CATEGORY in thresholds:
        threshold = thresholds[AT_RISK_PO_CATEGORY]
        evaluations = _at_risk_po_evaluations(
            session, simulation_date, _grace_days(threshold.threshold_value)
        )
        o, r = _sync_flags(
            session,
            category=AT_RISK_PO_CATEGORY,
            simulation_date=simulation_date,
            threshold_value=threshold.threshold_value,
            evaluations=evaluations,
        )
        opened += o
        resolved += r

    if LATE_SHIPMENT_CATEGORY in thresholds:
        threshold = thresholds[LATE_SHIPMENT_CATEGORY]
        evaluations = _late_shipment_evaluations(
            session, simulation_date, _grace_days(threshold.threshold_value)
        )
        o, r = _sync_flags(
            session,
            category=LATE_SHIPMENT_CATEGORY,
            simulation_date=simulation_date,
            threshold_value=threshold.threshold_value,
            evaluations=evaluations,
        )
        opened += o
        resolved += r

    if REPORTING_LAG_STALE_CATEGORY in thresholds:
        threshold = thresholds[REPORTING_LAG_STALE_CATEGORY]
        check = check_lag_staleness(
            session, simulation_date, max_lag_days=_grace_days(threshold.threshold_value)
        )
        o, r = _sync_flags(
            session,
            category=REPORTING_LAG_STALE_CATEGORY,
            simulation_date=simulation_date,
            threshold_value=threshold.threshold_value,
            evaluations={EntityKey(): Evaluation(check.is_stale, check.lag_days)},
        )
        opened += o
        resolved += r

    if REPORTING_CONFLICT_CATEGORY in thresholds:
        threshold = thresholds[REPORTING_CONFLICT_CATEGORY]
        conflict = check_reporting_conflict(session, tolerance_units=threshold.threshold_value)
        if conflict is not None:
            key = EntityKey(product_id=conflict.product_id, warehouse_id=conflict.warehouse_id)
            o, r = _sync_flags(
                session,
                category=REPORTING_CONFLICT_CATEGORY,
                simulation_date=simulation_date,
                threshold_value=threshold.threshold_value,
                evaluations={key: Evaluation(conflict.is_flagged, conflict.variance)},
            )
            opened += o
            resolved += r

    session.flush()

    still_open = session.execute(
        select(func.count())
        .select_from(ExceptionFlag)
        .where(ExceptionFlag.resolved_at.is_(None))
    ).scalar_one()

    return ExceptionEvaluationResult(
        simulation_date=simulation_date, opened=opened, resolved=resolved, still_open=still_open
    )
