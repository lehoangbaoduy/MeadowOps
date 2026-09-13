"""Default exception-rule thresholds (PRD S1-FR-4/S1-FR-10, spec
MEADOWOPS-DOMAIN-004). Builder-set defaults, pending Analyst review once
Active Use begins - not treated as final (PRD line 207).

Matches Unit 15's own title (MEADOWOPS-DOMAIN-007: "Exception engine
(at-risk PO / low stock / late shipment)") exactly - these are defaults for
precisely the three categories that engine will evaluate.

Idempotent: ON CONFLICT (id) DO NOTHING, same pattern as
app/services/baseline_data.py.
"""

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.exception_rules import ExceptionRuleThreshold

# low_stock_days_of_supply: grounded in the actual seeded supplier lead
# times (5-12 days, Unit 5's baseline data), not an arbitrary round number.
# 14 days is the slowest seeded supplier's replenishment time (S-005, 12
# days) plus a 2-day buffer, so a warehouse whose days-of-supply falls below
# its suppliers' own resupply time gets flagged before it actually runs out.
#
# at_risk_po_grace_days / late_shipment_grace_days: both default to 0 (flag
# immediately on breach, no grace period) - the simplest defensible
# starting point, deliberately left as something the Analyst has an actual
# number to iterate on (S1-FR-10: "refining at least one after observing
# real behavior") rather than a bare non-adjustable predicate.
EXCEPTION_RULE_THRESHOLDS = [
    {
        "id": "low_stock_days_of_supply",
        "name": "Low stock",
        "description": (
            "Flag a product/warehouse when days of supply (usable inventory "
            "divided by average daily usage) falls below this many days."
        ),
        "threshold_value": 14,
        "unit": "days",
        "is_active": True,
    },
    {
        "id": "at_risk_po_grace_days",
        "name": "At-risk purchase order",
        "description": (
            "Flag a purchase order as at-risk once its expected delivery "
            "date is this many days past the simulation date, if it isn't "
            "yet received or cancelled."
        ),
        "threshold_value": 0,
        "unit": "days",
        "is_active": True,
    },
    {
        "id": "late_shipment_grace_days",
        "name": "Late shipment",
        "description": (
            "Flag a shipment as late once its actual delivery date is this "
            "many days past its promised delivery date."
        ),
        "threshold_value": 0,
        "unit": "days",
        "is_active": True,
    },
    {
        "id": "reporting_lag_stale",
        "name": "Reporting layer stale",
        "description": (
            "Flag the Reporting layer as stale once it has gone this many "
            "days without syncing (PRD 9.2: a lag exceeding its expected "
            "window, e.g. simulated scheduler downtime)."
        ),
        "threshold_value": 5,
        "unit": "days",
        "is_active": True,
    },
    {
        "id": "reporting_conflict_qty_variance",
        "name": "Reporting/live quantity conflict",
        "description": (
            "Flag a product/warehouse whose Reporting-layer quantity-on-hand "
            "disagrees with live's own historical record for that same date "
            "by more than this many units (SR-4)."
        ),
        "threshold_value": 0,
        "unit": "units",
        "is_active": True,
    },
    {
        "id": "duplicate_purchase_order",
        "name": "Duplicate purchase order",
        "description": (
            "Flag an open purchase order as a likely accidental duplicate "
            "once more than this many open POs share the same supplier, "
            "warehouse, and expected delivery date (PRD 9.2 / SR-3)."
        ),
        "threshold_value": 1,
        "unit": "count",
        "is_active": True,
    },
]


def seed_exception_rule_thresholds(session: Session) -> None:
    stmt = (
        pg_insert(ExceptionRuleThreshold)
        .values(EXCEPTION_RULE_THRESHOLDS)
        .on_conflict_do_nothing()
    )
    session.execute(stmt)
    session.commit()
