"""Request/response schemas for Unit 8's admin master-data CRUD (PRD 5.6 /
S1-FR-12). Create/Update/Read are deliberately separate per-entity models
(coding-style.md: "keep request, update, and response schemas separate"),
not one model reused three ways.

`id` (and `sku` on Product) never appear in an *Update* schema — they are
business natural keys, immutable once created. baseline_data.py's seeder
relies on id == sku staying true for its bare `on_conflict_do_nothing()` to
keep meaning "no-op on either collision"; letting an edit diverge them would
silently break that the next time the seeder runs.

Field-level bounds (ge/le) mirror the DB's own CHECK constraints
(dimensions.py) so a bad value 422s before ever reaching Postgres. The one
constraint that can't be expressed as a single-field bound — Carrier's
transit_days_min <= transit_days_max — is enforced by the router after
merging a PATCH onto the existing row (schemas/`_validate_carrier` in
app/api/master_data.py), since a PATCH touching only one side of the pair
can't validate itself from the payload alone.
"""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

ProductCategory = Literal[
    "corrugated_packaging", "protective_packaging", "shipping_labeling_supplies"
]
CostTier = Literal["low", "mid", "high"]
Variability = Literal["low", "medium", "high"]


class ProductCreate(BaseModel):
    id: str = Field(min_length=1)
    sku: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: ProductCategory
    unit_cost: Decimal = Field(ge=0)
    is_active: bool = True


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    category: ProductCategory | None = None
    unit_cost: Decimal | None = Field(default=None, ge=0)
    is_active: bool | None = None


class ProductRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    sku: str
    name: str
    category: ProductCategory
    unit_cost: Decimal
    is_active: bool


class WarehouseCreate(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    region: str = Field(min_length=1)
    capacity_pallet_positions: int = Field(ge=0)
    is_active: bool = True


class WarehouseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    region: str | None = Field(default=None, min_length=1)
    capacity_pallet_positions: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class WarehouseRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    name: str
    region: str
    capacity_pallet_positions: int
    is_active: bool


class SupplierCreate(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category_focus: str = Field(min_length=1)
    unit_cost_tier: CostTier
    base_lead_time_days: int = Field(ge=0)
    lead_time_variability: Variability
    historical_otif_pct: Decimal = Field(ge=0, le=100)
    is_active: bool = True


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    category_focus: str | None = Field(default=None, min_length=1)
    unit_cost_tier: CostTier | None = None
    base_lead_time_days: int | None = Field(default=None, ge=0)
    lead_time_variability: Variability | None = None
    historical_otif_pct: Decimal | None = Field(default=None, ge=0, le=100)
    is_active: bool | None = None


class SupplierRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    name: str
    category_focus: str
    unit_cost_tier: CostTier
    base_lead_time_days: int
    lead_time_variability: Variability
    historical_otif_pct: Decimal
    is_active: bool


class CarrierCreate(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    transit_days_min: Decimal = Field(ge=0)
    transit_days_max: Decimal = Field(ge=0)
    variability: Variability
    reliability_pct: Decimal = Field(ge=0, le=100)
    is_active: bool = True


class CarrierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    transit_days_min: Decimal | None = Field(default=None, ge=0)
    transit_days_max: Decimal | None = Field(default=None, ge=0)
    variability: Variability | None = None
    reliability_pct: Decimal | None = Field(default=None, ge=0, le=100)
    is_active: bool | None = None


class CarrierRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    name: str
    transit_days_min: Decimal
    transit_days_max: Decimal
    variability: Variability
    reliability_pct: Decimal
    is_active: bool
