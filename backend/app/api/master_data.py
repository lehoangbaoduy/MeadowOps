"""Unit 8 (MEADOWOPS-API-002): admin panel master-data CRUD for
Product/Warehouse/Supplier/Carrier (PRD 5.6 / S1-FR-12) — Builder-only
(`require_builder`), list/create/edit/deactivate. No DELETE route: S1-FR-12
says "create, edit, deactivate", and every fact table (facts.py) holds a
non-deferrable FK to all four of these tables, so "deactivate" (PATCH
is_active=false) is the only removal semantics that exists.

Routes stay `def`, not `async def` — the whole stack underneath is sync
SQLAlchemy/psycopg (`Session`, not `AsyncSession`); an `async def` route
awaiting nothing while its body blocks on a sync DB call would stall the
event loop for every other in-flight request. `/health` and `/api/v1/me`
already establish this convention.

The spec (id 196) describes routes generically as `/api/v1/admin/{entity}`
— that was documentation shorthand for four parallel resources, not a
literal single dynamic-dispatch route. Four concrete typed routers (below,
via one shared `register_crud_routes` helper to avoid repeating the same
list/create/patch shape four times) keep each entity's Pydantic
validation/response typing explicit, rather than a stringly-typed `{entity}`
path param dispatching at runtime.
"""

from collections.abc import Callable
from typing import Any, TypeVar

import psycopg.errors as pg_errors
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import require_builder
from app.db.dimensions import Carrier, Product, Supplier, Warehouse
from app.db.session import get_session
from app.schemas.master_data import (
    CarrierCreate,
    CarrierRead,
    CarrierUpdate,
    ProductCreate,
    ProductRead,
    ProductUpdate,
    SupplierCreate,
    SupplierRead,
    SupplierUpdate,
    WarehouseCreate,
    WarehouseRead,
    WarehouseUpdate,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin-master-data"])

ModelT = TypeVar("ModelT")


def _register_crud_routes(
    path: str,
    model: type[ModelT],
    create_schema: type[BaseModel],
    update_schema: type[BaseModel],
    read_schema: type[BaseModel],
    validate_merged: Callable[[ModelT], None] | None = None,
) -> None:
    def list_records(
        session: Session = Depends(get_session),
        _identity: dict[str, str] = Depends(require_builder),
    ) -> list[Any]:
        return list(session.scalars(select(model).order_by(model.id)))

    def create_record(
        payload: create_schema,  # type: ignore[valid-type]
        session: Session = Depends(get_session),
        _identity: dict[str, str] = Depends(require_builder),
    ) -> Any:
        record = model(**payload.model_dump())
        if validate_merged is not None:
            validate_merged(record)
        session.add(record)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            if isinstance(exc.orig, pg_errors.UniqueViolation):
                field = _conflicting_field(exc, model)
                raise HTTPException(
                    status.HTTP_409_CONFLICT, detail=f"{model.__name__} {field} already exists"
                ) from exc
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"{model.__name__} violates a constraint"
            ) from exc
        session.refresh(record)
        return record

    def update_record(
        record_id: str,
        payload: update_schema,  # type: ignore[valid-type]
        session: Session = Depends(get_session),
        _identity: dict[str, str] = Depends(require_builder),
    ) -> Any:
        record = session.get(model, record_id)
        if record is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail=f"{model.__name__} not found"
            )
        updates = payload.model_dump(exclude_unset=True)
        # Security review of this unit: every field on these four entities
        # is NOT NULL at the DB (dimensions.py). Pydantic's `T | None =
        # Field(default=None, ...)` on an Update schema means "omittable",
        # but it also accepts an *explicit* JSON null, which bypasses the
        # ge/le field constraints (they only apply to the non-None branch of
        # the union) and would otherwise reach `_validate_carrier`'s `>`
        # comparison as a raw None, crashing with an unhandled TypeError
        # (500) instead of a 422 — reject it explicitly instead.
        null_fields = sorted(field for field, value in updates.items() if value is None)
        if null_fields:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Field(s) cannot be null: {', '.join(null_fields)}",
            )
        for field, value in updates.items():
            setattr(record, field, value)
        if validate_merged is not None:
            validate_merged(record)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"{model.__name__} update violates a constraint"
            ) from exc
        session.refresh(record)
        return record

    router.add_api_route(path, list_records, methods=["GET"], response_model=list[read_schema])
    router.add_api_route(
        path,
        create_record,
        methods=["POST"],
        response_model=read_schema,
        status_code=status.HTTP_201_CREATED,
    )
    router.add_api_route(
        path + "/{record_id}", update_record, methods=["PATCH"], response_model=read_schema
    )


def _conflicting_field(exc: IntegrityError, model: type) -> str:
    """Security review of this unit: reporting a flat "id already exists"
    on every UniqueViolation is inaccurate for Product, which also has a
    separate unique constraint on `sku` (dimensions.py) — a fresh id with a
    colliding sku would misleadingly claim the id collided. `Product` is the
    only one of the four entities with a second unique constraint today, so
    this stays a direct name check rather than a generic constraint-name
    parser."""
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    if model is Product and constraint == "product_sku_key":
        return "sku"
    return "id"


def _validate_carrier(carrier: Carrier) -> None:
    if carrier.transit_days_min > carrier.transit_days_max:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="transit_days_min must be <= transit_days_max",
        )


_register_crud_routes("/products", Product, ProductCreate, ProductUpdate, ProductRead)
_register_crud_routes("/warehouses", Warehouse, WarehouseCreate, WarehouseUpdate, WarehouseRead)
_register_crud_routes("/suppliers", Supplier, SupplierCreate, SupplierUpdate, SupplierRead)
_register_crud_routes(
    "/carriers", Carrier, CarrierCreate, CarrierUpdate, CarrierRead, validate_merged=_validate_carrier
)
