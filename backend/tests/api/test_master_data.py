"""Unit 8 (MEADOWOPS-API-002): admin panel master-data CRUD for
Product/Warehouse/Supplier/Carrier (PRD S1-FR-12), the first API endpoints
in this project that actually talk to Postgres (prior units only scaffolded
`/health` and `/api/v1/me`, DD-11's config-authority split named this unit
as the trigger for `Settings.database_url`).

S1-FR-12 says "create, edit, deactivate" — there is deliberately no DELETE
route. Every fact table (facts.py) holds a non-deferrable FK to all four of
these entities, so "deactivate" (PATCH is_active=false) is the only removal
semantics that exists.

All test rows use a `ZZTEST-` id prefix, distinct from both the seeded
baseline catalog (baseline_data.py: WH-EAST/S-00x/C-00x/SKU-xxx-0xx) and
other units' own `-TEST` fixtures, and are deleted in an autouse fixture
after every test — DD-9/DD-10 already burned this project once on leaked
test rows breaking a later migration/seeder.

Unit 17a (MEADOWOPS-DOM-010, DD-22): auth migrated from the single shared
Builder bearer token to signed session tokens minted via
tests/support/auth.py — list stays reachable by either role
(require_authenticated), create/update now require the admin role
(require_admin), so this file also covers the Analyst-gets-403 case that
require_builder's single shared token had no way to express.
"""

import os
from collections.abc import Generator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.dimensions import Carrier, Product, Supplier, Warehouse
from app.db.enums import PurchaseOrderStatus, SourceSystem
from app.db.facts import PurchaseOrder
from app.main import create_app
from tests.support.auth import TEST_SESSION_SECRET, make_token

_TOKEN = make_token("admin")
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}
_ANALYST_AUTH = {"Authorization": f"Bearer {make_token('analyst')}"}

_PRODUCT_ID = "ZZTEST-SKU-01"
_WAREHOUSE_ID = "ZZTEST-WH-01"
_SUPPLIER_ID = "ZZTEST-S-01"
_CARRIER_ID = "ZZTEST-C-01"

_ENTITY_PATHS = [
    "/api/v1/admin/products",
    "/api/v1/admin/warehouses",
    "/api/v1/admin/suppliers",
    "/api/v1/admin/carriers",
]


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    # `with` triggers the app's lifespan (creates app.state.engine) — a bare
    # TestClient(create_app()) would not, and every route in this file needs
    # a real DB session.
    with TestClient(create_app(settings=Settings(session_secret_key=TEST_SESSION_SECRET))) as c:
        yield c


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture(autouse=True)
def _cleanup_test_rows(db_session: Session) -> Generator[None, None, None]:
    yield
    db_session.execute(delete(PurchaseOrder).where(PurchaseOrder.supplier_id == _SUPPLIER_ID))
    db_session.execute(delete(Product).where(Product.id == _PRODUCT_ID))
    db_session.execute(delete(Product).where(Product.id == _PRODUCT_ID + "-DIFFERENT"))
    db_session.execute(delete(Warehouse).where(Warehouse.id == _WAREHOUSE_ID))
    db_session.execute(delete(Supplier).where(Supplier.id == _SUPPLIER_ID))
    db_session.execute(delete(Carrier).where(Carrier.id == _CARRIER_ID))
    db_session.commit()


@pytest.mark.parametrize("path", _ENTITY_PATHS)
def test_list_requires_auth(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 401


@pytest.mark.parametrize("path", _ENTITY_PATHS)
def test_create_requires_auth(client: TestClient, path: str) -> None:
    response = client.post(path, json={})
    assert response.status_code == 401


@pytest.mark.parametrize("path", _ENTITY_PATHS)
def test_list_is_reachable_by_the_analyst_role(client: TestClient, path: str) -> None:
    response = client.get(path, headers=_ANALYST_AUTH)
    assert response.status_code == 200


@pytest.mark.parametrize("path", _ENTITY_PATHS)
def test_create_is_forbidden_for_the_analyst_role(client: TestClient, path: str) -> None:
    response = client.post(path, json={}, headers=_ANALYST_AUTH)
    assert response.status_code == 403


@pytest.mark.parametrize("path", _ENTITY_PATHS)
def test_update_is_forbidden_for_the_analyst_role(client: TestClient, path: str) -> None:
    response = client.patch(f"{path}/does-not-matter", json={}, headers=_ANALYST_AUTH)
    assert response.status_code == 403


def test_create_product_then_appears_in_list(client: TestClient) -> None:
    payload = {
        "id": _PRODUCT_ID,
        "sku": _PRODUCT_ID,
        "name": "Test Widget",
        "category": "corrugated_packaging",
        "unit_cost": "1.50",
        "is_active": True,
    }
    create_response = client.post("/api/v1/admin/products", json=payload, headers=_AUTH)
    assert create_response.status_code == 201
    assert create_response.json()["id"] == _PRODUCT_ID

    list_response = client.get("/api/v1/admin/products", headers=_AUTH)
    assert list_response.status_code == 200
    assert any(row["id"] == _PRODUCT_ID for row in list_response.json())


def test_create_product_with_duplicate_id_returns_409(client: TestClient) -> None:
    payload = {
        "id": _PRODUCT_ID,
        "sku": _PRODUCT_ID,
        "name": "Test Widget",
        "category": "corrugated_packaging",
        "unit_cost": "1.50",
        "is_active": True,
    }
    first = client.post("/api/v1/admin/products", json=payload, headers=_AUTH)
    assert first.status_code == 201
    second = client.post("/api/v1/admin/products", json=payload, headers=_AUTH)
    assert second.status_code == 409


def test_create_product_with_negative_unit_cost_returns_422(client: TestClient) -> None:
    payload = {
        "id": _PRODUCT_ID,
        "sku": _PRODUCT_ID,
        "name": "Test Widget",
        "category": "corrugated_packaging",
        "unit_cost": "-1.00",
        "is_active": True,
    }
    response = client.post("/api/v1/admin/products", json=payload, headers=_AUTH)
    assert response.status_code == 422


def test_update_product_edits_name_and_persists(client: TestClient) -> None:
    payload = {
        "id": _PRODUCT_ID,
        "sku": _PRODUCT_ID,
        "name": "Original Name",
        "category": "corrugated_packaging",
        "unit_cost": "1.50",
        "is_active": True,
    }
    client.post("/api/v1/admin/products", json=payload, headers=_AUTH)

    patch_response = client.patch(
        f"/api/v1/admin/products/{_PRODUCT_ID}", json={"name": "Updated Name"}, headers=_AUTH
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["name"] == "Updated Name"

    get_response = client.get("/api/v1/admin/products", headers=_AUTH)
    row = next(r for r in get_response.json() if r["id"] == _PRODUCT_ID)
    assert row["name"] == "Updated Name"
    # Untouched fields survive the partial PATCH (exclude_unset) rather than
    # being reset to schema defaults.
    assert row["category"] == "corrugated_packaging"
    assert row["is_active"] is True


def test_update_product_ignores_id_and_sku_in_the_payload(client: TestClient) -> None:
    """id/sku are business natural keys, not in ProductUpdate's schema at
    all — baseline_data.py's seeder relies on id==sku staying true for its
    bare on_conflict_do_nothing() to keep working (see that module's
    docstring). A stray "sku" key in the request body must be silently
    ignored, not applied."""
    payload = {
        "id": _PRODUCT_ID,
        "sku": _PRODUCT_ID,
        "name": "Original Name",
        "category": "corrugated_packaging",
        "unit_cost": "1.50",
        "is_active": True,
    }
    client.post("/api/v1/admin/products", json=payload, headers=_AUTH)

    client.patch(
        f"/api/v1/admin/products/{_PRODUCT_ID}",
        json={"sku": "SOMETHING-ELSE", "id": "SOMETHING-ELSE"},
        headers=_AUTH,
    )

    get_response = client.get("/api/v1/admin/products", headers=_AUTH)
    row = next(r for r in get_response.json() if r["id"] == _PRODUCT_ID)
    assert row["sku"] == _PRODUCT_ID


def test_update_product_not_found_returns_404(client: TestClient) -> None:
    response = client.patch(
        "/api/v1/admin/products/NOT-A-REAL-ID", json={"name": "x"}, headers=_AUTH
    )
    assert response.status_code == 404


def test_deactivate_warehouse_flips_is_active_false(client: TestClient) -> None:
    payload = {
        "id": _WAREHOUSE_ID,
        "name": "Test Warehouse",
        "region": "Test Region",
        "capacity_pallet_positions": 1000,
        "is_active": True,
    }
    client.post("/api/v1/admin/warehouses", json=payload, headers=_AUTH)

    response = client.patch(
        f"/api/v1/admin/warehouses/{_WAREHOUSE_ID}", json={"is_active": False}, headers=_AUTH
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_create_warehouse_with_negative_capacity_returns_422(client: TestClient) -> None:
    payload = {
        "id": _WAREHOUSE_ID,
        "name": "Test Warehouse",
        "region": "Test Region",
        "capacity_pallet_positions": -1,
        "is_active": True,
    }
    response = client.post("/api/v1/admin/warehouses", json=payload, headers=_AUTH)
    assert response.status_code == 422


def test_create_supplier_with_otif_pct_over_100_returns_422(client: TestClient) -> None:
    payload = {
        "id": _SUPPLIER_ID,
        "name": "Test Supplier",
        "category_focus": "Corrugated Packaging",
        "unit_cost_tier": "mid",
        "base_lead_time_days": 7,
        "lead_time_variability": "low",
        "historical_otif_pct": "150.00",
        "is_active": True,
    }
    response = client.post("/api/v1/admin/suppliers", json=payload, headers=_AUTH)
    assert response.status_code == 422


def test_create_carrier_with_min_greater_than_max_returns_422(client: TestClient) -> None:
    payload = {
        "id": _CARRIER_ID,
        "name": "Test Carrier",
        "transit_days_min": "5.0",
        "transit_days_max": "3.0",
        "variability": "low",
        "reliability_pct": "95.0",
        "is_active": True,
    }
    response = client.post("/api/v1/admin/carriers", json=payload, headers=_AUTH)
    assert response.status_code == 422


def test_update_carrier_with_explicit_null_returns_422_not_500(client: TestClient) -> None:
    """Security review: an explicit JSON null on an Update field passes
    Pydantic's `T | None` validation (bypassing ge/le), then used to reach
    `_validate_carrier`'s `>` comparison as a raw None and crash with an
    unhandled TypeError (500) instead of a clean 422 — every field on these
    four entities is NOT NULL at the DB, so null is never a legitimate
    value to begin with."""
    payload = {
        "id": _CARRIER_ID,
        "name": "Test Carrier",
        "transit_days_min": "2.0",
        "transit_days_max": "4.0",
        "variability": "low",
        "reliability_pct": "95.0",
        "is_active": True,
    }
    client.post("/api/v1/admin/carriers", json=payload, headers=_AUTH)

    response = client.patch(
        f"/api/v1/admin/carriers/{_CARRIER_ID}",
        json={"transit_days_min": None},
        headers=_AUTH,
    )
    assert response.status_code == 422


def test_update_product_with_explicit_null_returns_422(client: TestClient) -> None:
    payload = {
        "id": _PRODUCT_ID,
        "sku": _PRODUCT_ID,
        "name": "Test Widget",
        "category": "corrugated_packaging",
        "unit_cost": "1.50",
        "is_active": True,
    }
    client.post("/api/v1/admin/products", json=payload, headers=_AUTH)

    response = client.patch(
        f"/api/v1/admin/products/{_PRODUCT_ID}", json={"name": None}, headers=_AUTH
    )
    assert response.status_code == 422


def test_create_product_with_colliding_sku_reports_sku_not_id(client: TestClient) -> None:
    """Security review: Product has a second unique constraint on `sku`
    independent of `id` (dimensions.py) — a collision there must not be
    reported as "id already exists"."""
    first = {
        "id": _PRODUCT_ID,
        "sku": _PRODUCT_ID,
        "name": "Test Widget",
        "category": "corrugated_packaging",
        "unit_cost": "1.50",
        "is_active": True,
    }
    client.post("/api/v1/admin/products", json=first, headers=_AUTH)

    second = {
        "id": _PRODUCT_ID + "-DIFFERENT",
        "sku": _PRODUCT_ID,
        "name": "Another Widget",
        "category": "corrugated_packaging",
        "unit_cost": "2.00",
        "is_active": True,
    }
    response = client.post("/api/v1/admin/products", json=second, headers=_AUTH)
    assert response.status_code == 409
    assert "sku" in response.json()["detail"]


def test_update_carrier_min_greater_than_existing_max_returns_422(client: TestClient) -> None:
    """Cross-field validity can't be checked from the PATCH payload alone
    when only one side of the pair is being edited — this exercises the
    merge-then-validate path (validated against the row's *existing* max),
    not the create-time schema validator."""
    payload = {
        "id": _CARRIER_ID,
        "name": "Test Carrier",
        "transit_days_min": "2.0",
        "transit_days_max": "4.0",
        "variability": "low",
        "reliability_pct": "95.0",
        "is_active": True,
    }
    client.post("/api/v1/admin/carriers", json=payload, headers=_AUTH)

    response = client.patch(
        f"/api/v1/admin/carriers/{_CARRIER_ID}",
        json={"transit_days_min": "5.0"},
        headers=_AUTH,
    )
    assert response.status_code == 422


def test_master_data_edit_does_not_rewrite_historical_purchase_order(
    client: TestClient, db_session: Session
) -> None:
    """PRD 5.6 / edge case catalog (9.2): "Master-data edit (Warehouse/
    Supplier/Carrier) applied mid-scenario -> historical scenario data
    referencing the old values is unchanged." A PurchaseOrder only stores
    supplier_id (facts.py has no denormalized copy of the supplier's own
    attributes), so this is a regression test proving that invariant holds
    through the new edit path, not a scenario-level test (that's Unit 30,
    once Subsystem 2 scenarios exist)."""
    supplier_payload = {
        "id": _SUPPLIER_ID,
        "name": "Test Supplier",
        "category_focus": "Corrugated Packaging",
        "unit_cost_tier": "mid",
        "base_lead_time_days": 7,
        "lead_time_variability": "low",
        "historical_otif_pct": "96.00",
        "is_active": True,
    }
    client.post("/api/v1/admin/suppliers", json=supplier_payload, headers=_AUTH)

    po = PurchaseOrder(
        po_number="ZZTEST-PO-01",
        supplier_id=_SUPPLIER_ID,
        warehouse_id="WH-EAST",
        order_date=date(2026, 1, 1),
        expected_delivery_date=date(2026, 1, 8),
        status=PurchaseOrderStatus.SUBMITTED,
        source_system=SourceSystem.PROCUREMENT,
    )
    db_session.add(po)
    db_session.commit()
    db_session.refresh(po)
    before = (po.id, po.supplier_id, po.order_date, po.expected_delivery_date, po.status)

    patch_response = client.patch(
        f"/api/v1/admin/suppliers/{_SUPPLIER_ID}",
        json={"base_lead_time_days": 30},
        headers=_AUTH,
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["base_lead_time_days"] == 30

    db_session.expire(po)
    after = (po.id, po.supplier_id, po.order_date, po.expected_delivery_date, po.status)
    assert before == after
    db_session.execute(text("DELETE FROM live.purchase_order WHERE po_number = 'ZZTEST-PO-01'"))
    db_session.commit()
