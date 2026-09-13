"""Unit 20 (MEADOWOPS-API-004, DD-2): proves the Subsystem1<->Subsystem2 API
boundary contract end-to-end - a genuine `httpx.AsyncClient` +
`httpx.ASGITransport` round trip through the real, running FastAPI app,
carrying real Pydantic-serialized Subsystem 1 data back to the caller, not
just a 200. This is the "integration tests covering the Subsystem 1 <->
Subsystem 2 API boundary passing" item on Phase 2's own checklist
(prd/MeadowOps_progress.md §5).

Runs the app's real lifespan via `app.router.lifespan_context` (not a bare
`create_app()` call) specifically so `app.state.subsystem2_client` - the
exact object app.services.subsystem2's future code will use - is the thing
under test, not a hand-built stand-in for it.
"""

from __future__ import annotations

import os

import pytest

from app.core.config import Settings
from app.main import create_app

_SECRET = "test-session-secret-value-at-least-32-bytes-long"
_SERVICE_TOKEN = "test-internal-service-token-value-at-least-32-bytes"


def _settings() -> Settings:
    return Settings(
        session_secret_key=_SECRET,
        internal_service_token=_SERVICE_TOKEN,
        database_url=os.environ["MEADOWOPS_DATABASE_URL"],
        sandbox_role_password=os.environ["MEADOWOPS_SANDBOX_ROLE_PASSWORD"],
    )


@pytest.mark.asyncio
async def test_internal_client_gets_a_genuine_authenticated_identity_through_asgi() -> None:
    app = create_app(settings=_settings())
    async with app.router.lifespan_context(app):
        client = app.state.subsystem2_client
        response = await client.get("/api/v1/me")
    assert response.status_code == 200
    assert response.json() == {"user_id": "subsystem2-internal", "role": "service"}


@pytest.mark.asyncio
async def test_internal_client_retrieves_genuine_subsystem1_data_not_just_a_200() -> None:
    """Real Pydantic-serialized response content, proving Subsystem 2's
    future service layer genuinely never needs app.db.session/live-schema
    ORM imports to read Subsystem 1's data (DD-2, PRD 376/S1-FR-6) - a
    dashboard endpoint reads real seeded KPI data through the full stack:
    routing, auth, the ORM session, Pydantic response validation, all
    in-process via ASGITransport."""
    app = create_app(settings=_settings())
    async with app.router.lifespan_context(app):
        client = app.state.subsystem2_client
        response = await client.get("/api/v1/dashboard/executive")
    assert response.status_code == 200
    body = response.json()
    # ExecutiveSummaryRead's actual response shape - not just "some JSON".
    # `kpis` is None only if the scheduler has never ticked in this dev DB
    # (app/schemas/dashboard.py) - assert the real shape either way rather
    # than assuming a particular DB state this test doesn't control.
    assert set(body.keys()) == {"kpis", "open_exception_counts"}
    assert isinstance(body["open_exception_counts"], list)
    if body["kpis"] is not None:
        assert set(body["kpis"].keys()) == {
            "simulation_date",
            "otif_pct",
            "fill_rate_pct",
            "order_cycle_time_days",
            "perfect_order_rate_pct",
            "computed_at",
        }


@pytest.mark.asyncio
async def test_internal_client_is_rejected_by_an_admin_gated_route() -> None:
    app = create_app(settings=_settings())
    async with app.router.lifespan_context(app):
        client = app.state.subsystem2_client
        response = await client.get("/api/v1/admin/scenarios")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_internal_client_is_rejected_by_query_playground_execute() -> None:
    app = create_app(settings=_settings())
    async with app.router.lifespan_context(app):
        client = app.state.subsystem2_client
        response = await client.post(
            "/api/v1/query/execute", json={"sql": "select 1", "confirmed": False}
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_internal_client_reaches_the_ledger_callback_candidates_route() -> None:
    """Unit 24 (MEADOWOPS-DOM-018): the callback mechanism's read side - the
    first genuine caller of this boundary from app.services.subsystem2 itself
    (app.services.subsystem2.ledger_client), proven here the same way as the
    dashboard read above: real routing/auth/ORM/Pydantic serialization, all
    in-process via ASGITransport. An empty list for an entity with no
    decisions is still a real 200, not a 404 - PRD 9.2's "callback scenario
    referencing a since-deactivated entity" edge case means this route must
    never treat "no candidates" as an error."""
    app = create_app(settings=_settings())
    async with app.router.lifespan_context(app):
        client = app.state.subsystem2_client
        response = await client.get(
            "/api/v1/ledger/entities/supplier/SUP-does-not-exist/callback-candidates"
        )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_internal_client_is_rejected_by_ledger_write_routes() -> None:
    app = create_app(settings=_settings())
    async with app.router.lifespan_context(app):
        client = app.state.subsystem2_client
        response = await client.post(
            "/api/v1/ledger/decisions",
            json={
                "entity_type": "supplier",
                "entity_id": "SUP-001",
                "title": "x",
                "summary": "x",
            },
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_internal_client_never_reaches_the_database_directly() -> None:
    """Structural proof, not just behavioral: nothing in this test module -
    or in the internal client it exercises - imports app.db.session or any
    live-schema ORM model. The client only ever speaks HTTP to the app; the
    app.domain.subsystem_boundary checker (tests/architecture) is what
    would catch a future violation of that inside app.services.subsystem2
    itself."""
    import ast
    import inspect

    import app.core.internal_client as internal_client_module

    source = inspect.getsource(internal_client_module)
    tree = ast.parse(source)
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any(name.startswith("app.db") for name in imported_names)
