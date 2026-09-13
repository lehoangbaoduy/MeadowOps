"""Pure decision logic for Unit 13's scheduled procure-to-stock /
order-to-ship flow (MEADOWOPS-DOM-006). No DB access here — the
transactional layer is app.services.scheduled_flow, same split as
app.domain.simulation_clock / app.services.simulation_clock_ops.

Product<->Supplier assignment is deterministic (not stored anywhere,
since no product_supplier table exists yet — computed fresh each call
from Supplier.category_focus, a free-text field that doesn't line up
1:1 with the ProductCategory enum, e.g. "Corrugated + Protective").
Randomness (demand generation, lead-time jitter) is seeded per
simulation_date + purpose so a given day's tick is reproducible.

Unit 27 (MEADOWOPS-DOM-021, business id MEADOWOPS-DOMAIN-016, PRD 3.4/5.2)
adds two more pieces of pure logic here: warehouse-transfer donor/deficit
math (warehouse_deficit / transferable_surplus / pick_transfer_donor) and
carrier-variability shipment lateness (carrier_actual_transit_days).
"""

import math
import random
from dataclasses import dataclass
from decimal import Decimal

from app.db.enums import ProductCategory, Variability

# Keyword(s) matched case-insensitively against Supplier.category_focus.
# Order matters only for readability; matching is keyword-membership, not
# positional.
_SUPPLIER_CATEGORY_KEYWORDS: dict[ProductCategory, tuple[str, ...]] = {
    ProductCategory.CORRUGATED_PACKAGING: ("corrugated",),
    ProductCategory.PROTECTIVE_PACKAGING: ("protective",),
    ProductCategory.SHIPPING_LABELING_SUPPLIES: ("shipping", "labeling"),
}

# A product with zero recent demand still needs a first PO — this is the
# floor that makes day-one bootstrapping happen (starting inventory
# position is 0 for everything, since no InventorySnapshot/
# InventoryTransaction rows exist until this unit creates them).
BOOTSTRAP_REORDER_THRESHOLD = 10
MINIMUM_REORDER_QUANTITY = 20
DEMAND_LOOKBACK_DAYS = 14

# Shared by jittered_lead_time_days (supplier lead time, +/- either
# direction) and carrier_actual_transit_days (carrier lateness, late-only)
# -- both scale jitter to the same three-tier Variability enum.
_VARIABILITY_SPREAD_DAYS: dict[Variability, int] = {
    Variability.LOW: 1,
    Variability.MEDIUM: 3,
    Variability.HIGH: 6,
}


class NoMatchingSupplierError(RuntimeError):
    """Raised when no active supplier's category_focus matches a product's
    category — a genuine data-setup gap, not swallowed silently."""


@dataclass(frozen=True)
class SupplierCandidate:
    id: str
    category_focus: str


def assign_supplier(
    product_category: ProductCategory, suppliers: list[SupplierCandidate]
) -> SupplierCandidate:
    """Deterministic: same product category always resolves to the same
    supplier (the lowest id among keyword matches), so repeated ticks don't
    scatter one product's POs across different suppliers for no reason."""
    keywords = _SUPPLIER_CATEGORY_KEYWORDS[product_category]
    matches = [
        s
        for s in suppliers
        if any(kw in s.category_focus.lower() for kw in keywords)
    ]
    if not matches:
        raise NoMatchingSupplierError(
            f"no active supplier's category_focus matches {product_category.value}"
        )
    return min(matches, key=lambda s: s.id)


def jittered_lead_time_days(base_days: int, variability: Variability, rng: random.Random) -> int:
    """Adds +/- jitter scaled to the supplier's lead_time_variability tier.
    Floored at 1 day — an order can't arrive before it's placed."""
    spread = _VARIABILITY_SPREAD_DAYS[variability]
    jitter = rng.randint(-spread, spread)
    return max(1, base_days + jitter)


def carrier_actual_transit_days(
    promised_transit_days: int, variability: Variability, reliability_pct: float, rng: random.Random
) -> int:
    """Uses reliability_pct as the probability a shipment arrives exactly on
    its promised transit time; the rest of the time it arrives late by 1..
    spread days (spread scaled to the carrier's variability tier), never
    early. Matches the PRD's carrier table, which frames reliability_pct as
    an on-time rate (e.g. "~91% on-time"), not a symmetric jitter the way
    jittered_lead_time_days's supplier lead time is."""
    if rng.uniform(0, 100) < reliability_pct:
        return promised_transit_days
    spread = _VARIABILITY_SPREAD_DAYS[variability]
    return promised_transit_days + rng.randint(1, spread)


# Unit 30 (MEADOWOPS-DOM-030, PRD 9.2 catalog row 4): PurchaseOrderStatus.
# PARTIALLY_RECEIVED already existed in the enum but was never produced by
# any code path (app.services.scheduled_flow._progress_purchase_orders
# always received every line in full). This makes short-receive a real,
# seeded possibility, same "reproducible per simulation_date+purpose"
# discipline as carrier_actual_transit_days above.
_PARTIAL_RECEIPT_CHANCE = 0.2
_PARTIAL_RECEIPT_MIN_FRACTION = Decimal("0.5")
_PARTIAL_RECEIPT_MAX_FRACTION = Decimal("0.9")


def roll_partial_receipt_fraction(rng: random.Random) -> Decimal | None:
    """Returns None for a full receipt (the common case, ~80% of the time),
    or a Decimal fraction in [0.5, 0.9) of each line's remaining quantity
    to receive on this tick, leaving the rest for a later tick."""
    if rng.random() >= _PARTIAL_RECEIPT_CHANCE:
        return None
    span = _PARTIAL_RECEIPT_MAX_FRACTION - _PARTIAL_RECEIPT_MIN_FRACTION
    return _PARTIAL_RECEIPT_MIN_FRACTION + Decimal(str(round(rng.random(), 4))) * span


def reorder_quantity(avg_daily_demand: float, target_days_of_supply: int) -> int:
    """Ceil'd so a fractional average demand never under-orders, floored at
    MINIMUM_REORDER_QUANTITY so a product with barely-any observed demand
    still gets a meaningful restock rather than a token 1-2 units."""
    return max(MINIMUM_REORDER_QUANTITY, math.ceil(avg_daily_demand * target_days_of_supply))


def _reorder_threshold(avg_daily_demand: float, reorder_safety_days: int) -> float:
    """Falls back to BOOTSTRAP_REORDER_THRESHOLD when there's no demand
    history yet, so a genuinely new product (0 demand, 0 position) still
    triggers its first PO instead of waiting indefinitely for a
    chicken-and-egg demand signal that can only come from a PO existing in
    the first place."""
    return max(avg_daily_demand * reorder_safety_days, BOOTSTRAP_REORDER_THRESHOLD)


def is_below_reorder_point(
    current_position: int, avg_daily_demand: float, reorder_safety_days: int
) -> bool:
    """True when current stock would run out within reorder_safety_days at
    the recently observed demand rate."""
    return current_position < _reorder_threshold(avg_daily_demand, reorder_safety_days)


def warehouse_deficit(
    current_position: int, avg_daily_demand: float, reorder_safety_days: int
) -> int:
    """0 once at/above the same reorder threshold is_below_reorder_point
    checks against; otherwise the ceil'd shortfall — how many units a
    warehouse transfer (or PO) would need to bring the position back up to
    it."""
    shortfall = _reorder_threshold(avg_daily_demand, reorder_safety_days) - current_position
    return max(0, math.ceil(shortfall))


def transferable_surplus(
    current_position: int, allocated: int, avg_daily_demand: float, reorder_safety_days: int
) -> int:
    """How much of a warehouse's unallocated stock it can give away as a
    transfer donor without dropping below its own reorder threshold.
    Floored (not ceil'd, unlike warehouse_deficit) so a donor is never
    credited with more than it can actually spare."""
    spare = current_position - allocated - _reorder_threshold(avg_daily_demand, reorder_safety_days)
    return max(0, math.floor(spare))


def pick_transfer_donor(candidates: list[tuple[str, int]]) -> tuple[str, int] | None:
    """Picks the (warehouse_id, transferable_surplus) candidate with the
    greatest surplus, breaking ties by the lowest warehouse_id so the
    choice is deterministic. None when no candidate has anything to
    spare."""
    positive = [c for c in candidates if c[1] > 0]
    if not positive:
        return None
    return min(positive, key=lambda c: (-c[1], c[0]))


def pick_demand_products(rng: random.Random, product_ids: list[str]) -> list[str]:
    """1-3 distinct products for one customer's new order on one day."""
    if not product_ids:
        return []
    count = rng.randint(1, min(3, len(product_ids)))
    return rng.sample(product_ids, count)


def pick_demand_quantity(rng: random.Random, *, min_qty: int = 1, max_qty: int = 20) -> int:
    return rng.randint(min_qty, max_qty)


def pick_requested_date_offset(rng: random.Random, *, min_days: int = 1, max_days: int = 3) -> int:
    return rng.randint(min_days, max_days)
