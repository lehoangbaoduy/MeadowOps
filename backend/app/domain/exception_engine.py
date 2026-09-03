"""Pure decision logic for Unit 15's exception engine (MEADOWOPS-DOM-008).
No DB access here — the transactional layer is app.services.exception_engine,
same split as app.domain.scheduled_flow / app.services.scheduled_flow.

Three categories, matching the three default rows Unit 10 seeded into
live.exception_rule_threshold exactly (low_stock_days_of_supply,
at_risk_po_grace_days, late_shipment_grace_days) — the threshold values
themselves are Analyst-adjustable (S1-FR-10) and read fresh from that
table by the service layer, never hardcoded here.
"""

from datetime import date
from decimal import Decimal

from app.db.enums import PurchaseOrderStatus, ShipmentStatus

_PURCHASE_ORDER_CLOSED_STATUSES = frozenset(
    {PurchaseOrderStatus.RECEIVED, PurchaseOrderStatus.CANCELLED}
)


def evaluate_low_stock(days_of_supply: Decimal | None, *, threshold_days: Decimal) -> bool:
    """Flags a product/warehouse whose days-of-supply has fallen below the
    threshold. `None` means the ratio is undefined (no shipment activity in
    the trailing 30 days — see sql/kpi/days_of_supply.sql's NULLIF guard),
    not "zero days of supply" — an undefined value is never flagged, the
    same graceful-degradation posture Unit 10 already committed to."""
    if days_of_supply is None:
        return False
    return days_of_supply < threshold_days


def evaluate_at_risk_purchase_order(
    *,
    expected_delivery_date: date,
    simulation_date: date,
    grace_days: int,
    status: PurchaseOrderStatus,
) -> bool:
    """Flags a purchase order that is still open (not RECEIVED/CANCELLED —
    PARTIALLY_RECEIVED still counts as open, since the remainder is still
    outstanding) once simulation_date passes expected_delivery_date plus
    the grace period."""
    if status in _PURCHASE_ORDER_CLOSED_STATUSES:
        return False
    return (simulation_date - expected_delivery_date).days > grace_days


def evaluate_late_shipment(
    *,
    promised_delivery_date: date,
    actual_delivery_date: date | None,
    simulation_date: date,
    grace_days: int,
    status: ShipmentStatus,
) -> bool:
    """Flags a shipment as late once it's this many days past its promised
    delivery date. A delivered shipment is judged against its actual
    delivery date (a fixed, final fact); an undelivered one is judged
    against the current simulation_date (a moving target re-evaluated each
    tick, since it might still arrive within grace, or might not)."""
    if status == ShipmentStatus.DELIVERED:
        if actual_delivery_date is None:
            return False
        return (actual_delivery_date - promised_delivery_date).days > grace_days
    return (simulation_date - promised_delivery_date).days > grace_days
