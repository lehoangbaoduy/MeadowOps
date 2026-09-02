"""Unit 12c (MEADOWOPS-API-006): read-only Customer listing (PRD Appendix
D.1, "Customers (e-commerce) -> Customer master data: Direct entity
match"). GET only — S1-FR-12 names only Warehouse/Supplier/Carrier for
admin CRUD, so unlike tests/api/test_master_data.py there is no create/
update path to exercise here, and nothing for an autouse cleanup fixture to
delete: this endpoint never writes.
"""

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

_TOKEN = "test-builder-token-value"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}

# Unit 5's baseline_data.py seeds these 9 customers for real — containment
# check against real seeded data, same convention as
# tests/services/test_baseline_data.py, not a hand-inserted fixture row.
_SEEDED_CUSTOMER_IDS = {
    "CUST-EAST-01",
    "CUST-EAST-02",
    "CUST-EAST-03",
    "CUST-CENTRAL-01",
    "CUST-CENTRAL-02",
    "CUST-CENTRAL-03",
    "CUST-WEST-01",
    "CUST-WEST-02",
    "CUST-WEST-03",
}


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(create_app(settings=Settings(builder_token=_TOKEN))) as c:
        yield c


def test_list_requires_builder_auth(client: TestClient) -> None:
    response = client.get("/api/v1/admin/customers")
    assert response.status_code == 401


def test_list_returns_the_seeded_baseline_customers(client: TestClient) -> None:
    response = client.get("/api/v1/admin/customers", headers=_AUTH)
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert _SEEDED_CUSTOMER_IDS <= ids


def test_list_response_shape_matches_customer_read_schema(client: TestClient) -> None:
    response = client.get("/api/v1/admin/customers", headers=_AUTH)
    assert response.status_code == 200  # a clear failure here beats a StopIteration below
    row = next(r for r in response.json() if r["id"] == "CUST-EAST-01")
    # Values from baseline_data.py's CUSTOMERS list (Unit 5) — real seeded
    # data, not a hand-picked fixture.
    assert row == {
        "id": "CUST-EAST-01",
        "name": "Harborline Distribution",
        "service_priority": "priority",
        "warehouse_id": "WH-EAST",
        "region": "Northeast US",
        "is_active": True,
    }


def test_there_is_no_write_route_for_customers(client: TestClient) -> None:
    # The absence itself is the point (S1-FR-12 excludes Customer from
    # admin CRUD) — a 405/404 either way proves no POST handler was
    # accidentally wired up via router include-order or a copy-paste from
    # master_data.py's _register_crud_routes pattern.
    response = client.post("/api/v1/admin/customers", json={}, headers=_AUTH)
    assert response.status_code in (404, 405)
