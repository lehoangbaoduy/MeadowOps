"""Unit 12c (MEADOWOPS-API-006): read-only Customer listing for orbynadmin's
Customers page (PRD Appendix D.1: "Direct entity match", no CRUD
requirement — S1-FR-12 names only Warehouse/Supplier/Carrier for admin
CRUD). GET only, deliberately: this is the one Appendix D page with real,
non-empty seeded data available in Phase 1 (Unit 5's 9 baseline customers) —
Inventory/Orders/Shipping/Activity stay EmptyState stubs until their own
data-populating units (U13, U24) land, per the Phase 1 checklist scoping
in the progress doc (B7/DD-17).

Builder-only (require_builder), same convention as app/api/master_data.py.
`def`, not `async def` — same sync-SQLAlchemy-under-the-event-loop
rationale as that module.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import require_builder
from app.db.dimensions import Customer
from app.db.session import get_session
from app.schemas.customers import CustomerRead

router = APIRouter(prefix="/api/v1/admin", tags=["admin-customers"])


@router.get("/customers", response_model=list[CustomerRead])
def list_customers(
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_builder),
) -> list[Customer]:
    return list(session.scalars(select(Customer).order_by(Customer.id)))
