"""Read schema for Unit 12c (MEADOWOPS-API-006): Customer is deliberately
not part of Unit 8's master-data CRUD (app/schemas/master_data.py) — S1-FR-12
names only Warehouse/Supplier/Carrier for admin CRUD, and Appendix D's
mapping for the Customers page says "Direct entity match" with no CRUD
requirement. Read-only, kept in its own file rather than folded into
master_data.py, since that module's own docstring specifically frames
itself around Create/Update/Read triads for the four CRUD entities.
"""

from typing import Literal

from pydantic import BaseModel

ServicePriority = Literal["standard", "priority", "critical"]


class CustomerRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    name: str
    service_priority: ServicePriority
    warehouse_id: str
    region: str
    is_active: bool
