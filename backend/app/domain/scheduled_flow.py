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
"""

import math
import random
from dataclasses import dataclass

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
    spread = {Variability.LOW: 1, Variability.MEDIUM: 3, Variability.HIGH: 6}[variability]
    jitter = rng.randint(-spread, spread)
    return max(1, base_days + jitter)


def reorder_quantity(avg_daily_demand: float, target_days_of_supply: int) -> int:
    """Ceil'd so a fractional average demand never under-orders, floored at
    MINIMUM_REORDER_QUANTITY so a product with barely-any observed demand
    still gets a meaningful restock rather than a token 1-2 units."""
    return max(MINIMUM_REORDER_QUANTITY, math.ceil(avg_daily_demand * target_days_of_supply))


def is_below_reorder_point(
    current_position: int, avg_daily_demand: float, reorder_safety_days: int
) -> bool:
    """True when current stock would run out within reorder_safety_days at
    the recently observed demand rate. Falls back to
    BOOTSTRAP_REORDER_THRESHOLD when there's no demand history yet, so a
    genuinely new product (0 demand, 0 position) still triggers its first
    PO instead of waiting indefinitely for a chicken-and-egg demand signal
    that can only come from a PO existing in the first place."""
    threshold = max(avg_daily_demand * reorder_safety_days, BOOTSTRAP_REORDER_THRESHOLD)
    return current_position < threshold


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
