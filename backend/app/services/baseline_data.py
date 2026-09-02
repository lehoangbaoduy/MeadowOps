"""Baseline data generator (PRD Section 3, spec MEADOWOPS-PROD-001).

Master-data content (warehouses, suppliers, carriers) is transcribed
directly from PRD 3.2/3.3/3.4 — those tables are the source of truth, not a
design decision. The exact SKU catalog and starter customer list are **not**
specified by the PRD beyond "~20 SKUs across 3 categories" and "represented
through Sales Orders" — both are this module's own design decision, recorded
in prd/MeadowOps_progress.md.

Idempotent: every insert is ON CONFLICT (id) DO NOTHING, so re-running
against an already-seeded database is a no-op, not a duplicate.
"""

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.dimensions import Carrier, Customer, Product, Supplier, Warehouse

WAREHOUSES = [
    {
        "id": "WH-EAST",
        "name": "East Warehouse",
        "region": "Northeast US",
        "capacity_pallet_positions": 4000,
        "is_active": True,
    },
    {
        "id": "WH-CENTRAL",
        "name": "Central Warehouse",
        "region": "Midwest US",
        "capacity_pallet_positions": 6000,
        "is_active": True,
    },
    {
        "id": "WH-WEST",
        "name": "West Warehouse",
        "region": "Southwest US",
        "capacity_pallet_positions": 3000,
        "is_active": True,
    },
]

# lead_time_variability for S-004 is set to "medium" as a categorical
# baseline — the PRD table gives it a narrative drift ("~6 to ~12 days over
# six weeks") instead of a Low/Medium/High label like the other five
# suppliers. The drift itself is simulated dynamically by the root-cause
# storyline unit (Phase 2/3), not encoded as a static field here.
SUPPLIERS = [
    {
        "id": "S-001",
        "name": "Vantage Corrugated Co.",
        "category_focus": "Corrugated Packaging",
        "unit_cost_tier": "mid",
        "base_lead_time_days": 7,
        "lead_time_variability": "low",
        "historical_otif_pct": 96.0,
        "is_active": True,
    },
    {
        "id": "S-002",
        "name": "Palmetto Protective Supply",
        "category_focus": "Protective Packaging",
        "unit_cost_tier": "low",
        "base_lead_time_days": 10,
        "lead_time_variability": "medium",
        "historical_otif_pct": 89.0,
        "is_active": True,
    },
    {
        "id": "S-003",
        "name": "Ironclad Freight Materials",
        "category_focus": "Shipping/Labeling Supplies",
        "unit_cost_tier": "mid",
        "base_lead_time_days": 5,
        "lead_time_variability": "low",
        "historical_otif_pct": 97.0,
        "is_active": True,
    },
    {
        "id": "S-004",
        "name": "Meridian Packaging Partners",
        "category_focus": "Corrugated + Protective",
        "unit_cost_tier": "high",
        "base_lead_time_days": 6,
        "lead_time_variability": "medium",
        "historical_otif_pct": 93.0,
        "is_active": True,
    },
    {
        "id": "S-005",
        "name": "Coastal Supply Exchange",
        "category_focus": "Shipping/Labeling Supplies",
        "unit_cost_tier": "low",
        "base_lead_time_days": 12,
        "lead_time_variability": "high",
        "historical_otif_pct": 82.0,
        "is_active": True,
    },
    {
        "id": "S-006",
        "name": "Timber & Twine Co.",
        "category_focus": "Protective Packaging (niche)",
        "unit_cost_tier": "high",
        "base_lead_time_days": 9,
        "lead_time_variability": "low",
        "historical_otif_pct": 95.0,
        "is_active": True,
    },
]

CARRIERS = [
    {
        "id": "C-001",
        "name": "Ridgeline Freight Lines",
        "transit_days_min": 2,
        "transit_days_max": 2,
        "variability": "low",
        "reliability_pct": 98.0,
        "is_active": True,
    },
    {
        "id": "C-002",
        "name": "Summit National Carriers",
        "transit_days_min": 3,
        "transit_days_max": 4,
        "variability": "medium",
        "reliability_pct": 91.0,
        "is_active": True,
    },
    {
        "id": "C-003",
        "name": "ValueHaul Logistics",
        "transit_days_min": 4,
        "transit_days_max": 5,
        "variability": "high",
        "reliability_pct": 85.0,
        "is_active": True,
    },
]

# Design decision (not PRD-specified beyond "~20 SKUs across 3 categories",
# PRD 3.1): this catalog. 7 + 7 + 6 = 20.
_CORRUGATED = [
    ("SKU-COR-001", "Small Shipping Box 12x9x6", 0.85),
    ("SKU-COR-002", "Medium Shipping Box 16x12x10", 1.35),
    ("SKU-COR-003", "Large Shipping Box 20x16x14", 2.10),
    ("SKU-COR-004", "Heavy-Duty Double-Wall Box", 3.40),
    ("SKU-COR-005", "Corrugated Sheets (flat)", 0.60),
    ("SKU-COR-006", "Die-Cut Mailer Box", 1.05),
    ("SKU-COR-007", "Corrugated Pallet Sleeve", 4.50),
]
_PROTECTIVE = [
    ("SKU-PRO-001", "Bubble Mailer - Small", 0.25),
    ("SKU-PRO-002", "Bubble Mailer - Large", 0.45),
    ("SKU-PRO-003", "Foam Corner Protectors (set)", 0.90),
    ("SKU-PRO-004", "Bubble Wrap Roll", 12.00),
    ("SKU-PRO-005", "Void-Fill Air Pillows (bag)", 8.50),
    ("SKU-PRO-006", "Foam Sheeting Roll", 15.00),
    ("SKU-PRO-007", "Kraft Paper Void-Fill (bundle)", 6.75),
]
_SHIPPING_LABELING = [
    ("SKU-SHP-001", "Packing Tape - Clear", 3.20),
    ("SKU-SHP-002", "Packing Tape - Reinforced", 4.10),
    ("SKU-SHP-003", "Shipping Labels - Thermal 4x6 (roll)", 5.50),
    ("SKU-SHP-004", "Stretch Wrap Roll", 9.25),
    ("SKU-SHP-005", "Fragile Warning Labels (roll)", 2.75),
    ("SKU-SHP-006", "Address Label Sheets (pack)", 3.90),
]

PRODUCTS = [
    {"id": sku, "sku": sku, "name": name, "category": "corrugated_packaging", "unit_cost": cost, "is_active": True}
    for sku, name, cost in _CORRUGATED
] + [
    {"id": sku, "sku": sku, "name": name, "category": "protective_packaging", "unit_cost": cost, "is_active": True}
    for sku, name, cost in _PROTECTIVE
] + [
    {"id": sku, "sku": sku, "name": name, "category": "shipping_labeling_supplies", "unit_cost": cost, "is_active": True}
    for sku, name, cost in _SHIPPING_LABELING
]

# Design decision (not PRD-specified beyond "represented through Sales
# Orders (ID, name, service priority, warehouse assignment, region, order
# history)", PRD 3.5): 3 starter customers per warehouse, 9 total.
CUSTOMERS = [
    {"id": "CUST-EAST-01", "name": "Harborline Distribution", "service_priority": "priority", "warehouse_id": "WH-EAST", "region": "Northeast US", "is_active": True},
    {"id": "CUST-EAST-02", "name": "Brookfield Retail Supply", "service_priority": "standard", "warehouse_id": "WH-EAST", "region": "Northeast US", "is_active": True},
    {"id": "CUST-EAST-03", "name": "Union Square Fulfillment", "service_priority": "critical", "warehouse_id": "WH-EAST", "region": "Northeast US", "is_active": True},
    {"id": "CUST-CENTRAL-01", "name": "Heartland Logistics Co.", "service_priority": "priority", "warehouse_id": "WH-CENTRAL", "region": "Midwest US", "is_active": True},
    {"id": "CUST-CENTRAL-02", "name": "Prairie Pack & Ship", "service_priority": "standard", "warehouse_id": "WH-CENTRAL", "region": "Midwest US", "is_active": True},
    {"id": "CUST-CENTRAL-03", "name": "Great Lakes Wholesale", "service_priority": "standard", "warehouse_id": "WH-CENTRAL", "region": "Midwest US", "is_active": True},
    {"id": "CUST-WEST-01", "name": "Desert Sun Retailers", "service_priority": "standard", "warehouse_id": "WH-WEST", "region": "Southwest US", "is_active": True},
    {"id": "CUST-WEST-02", "name": "Cascade Fulfillment Partners", "service_priority": "priority", "warehouse_id": "WH-WEST", "region": "Southwest US", "is_active": True},
    {"id": "CUST-WEST-03", "name": "Mesa Verde Supply Chain", "service_priority": "standard", "warehouse_id": "WH-WEST", "region": "Southwest US", "is_active": True},
]


def _upsert_ignore(session: Session, model: type, rows: list[dict]) -> None:
    if not rows:
        return
    # No index_elements: a bare on_conflict_do_nothing() ignores a conflict
    # on *any* unique/PK constraint on the target table, not just `id`.
    # Product also has a separate unique constraint on `sku` (code review of
    # this unit) — id==sku for every seeded row today, but the moment a
    # future admin-panel edit (PRD 5.6) makes them diverge, an id-scoped
    # conflict target would raise UniqueViolation on the sku collision
    # instead of the no-op this function promises.
    stmt = pg_insert(model).values(rows).on_conflict_do_nothing()
    session.execute(stmt)


def seed_master_data(session: Session) -> None:
    """Warehouses, suppliers, and carriers first (customers/products
    reference warehouses via FK; PurchaseOrder/SalesOrder reference
    suppliers/customers, but those transactional facts are not this
    function's job — see Unit 13, the scheduled procure-to-stock/
    order-to-ship flow)."""
    _upsert_ignore(session, Warehouse, WAREHOUSES)
    _upsert_ignore(session, Supplier, SUPPLIERS)
    _upsert_ignore(session, Carrier, CARRIERS)
    _upsert_ignore(session, Product, PRODUCTS)
    _upsert_ignore(session, Customer, CUSTOMERS)
    session.commit()
