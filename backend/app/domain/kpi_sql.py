"""Starter KPI SQL loader (PRD Appendix A, S1-FR-3/S1-FR-11, spec
MEADOWOPS-DOMAIN-004).

The queries themselves live as plain `.sql` files under `sql/kpi/`, not as
a database table: PRD line 163 calls the KPI definitions "versioned
thereafter" once the Builder implements them, and source-control history
already provides that versioning without inventing a schema this module has
no reader for yet - Unit 14 (the real KPI engine, MEADOWOPS-DOMAIN-006) is
what will actually execute these and is free to restructure how they're
stored once it knows how it needs to consume them (same reasoning as
declining a query_log table at Unit 9 before anything read from it).

Every query here is a Builder-set placeholder pending Analyst review (PRD
line 207) - not a final calculation.
"""

from pathlib import Path

_SQL_DIR = Path(__file__).resolve().parents[2] / "sql" / "kpi"

KPI_NAMES = (
    "otif",
    "fill_rate",
    "days_of_supply",
    "order_cycle_time",
    "perfect_order_rate",
)


def load_kpi_sql(name: str) -> str:
    if name not in KPI_NAMES:
        raise ValueError(f"unknown KPI name: {name!r} (expected one of {KPI_NAMES})")
    return (_SQL_DIR / f"{name}.sql").read_text()
