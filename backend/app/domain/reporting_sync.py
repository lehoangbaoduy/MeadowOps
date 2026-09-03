"""Unit 17 (MEADOWOPS-DOM-009): pure decision logic for the deliberately
lagged Reporting layer (PRD 4.1, S1-FR-9, SR-2) and its one seeded
conflicting-source case (SR-4). No DB access here — the transactional
layer is app.services.reporting_sync, same split as
app.domain.scheduled_flow / app.services.scheduled_flow.

SR-1 (inconsistent formatting) and SR-3's duplicate/orphaned-reference
edge cases are explicitly out of scope for this unit — see the progress
doc's U17 entry: neither has a Phase 2 checklist hook, and 9.2's specific
duplicate/orphaned-FK rows sit under Phase 3's own "full edge case catalog"
item, not this one's "reporting-layer lag implemented" / "at least one
seeded conflicting-source or bad-data case" pair.
"""

from datetime import date, timedelta

# Fixed, deterministic corruption applied once to the seeded conflict
# entity's one-and-only reporting row (app.services.reporting_sync) — not
# re-derived from live on every sync, so the discrepancy is a frozen
# artifact of one bad sync rather than a systematic, invertible transform
# a later formula fix could quietly resolve.
KNOWN_CONFLICT_QTY_OFFSET = 25


def target_sync_date(simulation_date: date, *, lag_days: int) -> date:
    """The live snapshot_date the Reporting layer should be caught up to
    as of this simulation_date — a steady-state lag of `lag_days`, not a
    fixed lookback window."""
    return simulation_date - timedelta(days=lag_days)


def is_lag_stale(
    *, simulation_date: date, last_synced_simulation_date: date | None, max_lag_days: int
) -> bool:
    """PRD 9.2: "Reporting-layer lag exceeding its expected window
    (simulated scheduler downtime)" must be detected and surfaced, not
    silently masked as normal latency.

    `last_synced_simulation_date=None` (the layer has never synced) is
    never flagged stale — before the very first sync there is no live
    history yet for the Reporting layer to lag behind, so "hasn't synced"
    isn't evidence of a broken sync any more than an undefined
    days-of-supply ratio is evidence of low stock
    (app.domain.exception_engine.evaluate_low_stock). A genuinely stuck
    sync only becomes visible once simulation_date has actually moved on
    without it.

    Strict greater-than, not >=, matching evaluate_at_risk_purchase_order/
    evaluate_late_shipment's own grace-period convention: the boundary
    itself is still within the configured window."""
    if last_synced_simulation_date is None:
        return False
    lag_days = (simulation_date - last_synced_simulation_date).days
    return lag_days > max_lag_days


def pick_conflict_entity(
    candidates: list[tuple[str, str]],
) -> tuple[str, str] | None:
    """Deterministically designates one (product_id, warehouse_id) pair as
    the permanent SR-4 conflicting-source case, out of whatever pairs are
    available on the Reporting layer's first-ever sync. Lexicographically
    smallest, not random — a demo/test run must always corrupt the same
    entity given the same seeded data, the same determinism convention
    app.services.scheduled_flow._pick_carrier already uses for shipment
    carrier assignment."""
    if not candidates:
        return None
    return min(candidates)
