"""Unit 30c (MEADOWOPS-UI-005, security review): regression test for the
no-Content-Length (real chunked transfer) path of MaxBodySizeMiddleware -
see app.core.body_size_limit's own module docstring for the full trace of
why the response here is FastAPI's generic 400, not this module's 413.

Lives under tests/integration/, not tests/api/test_chat_api.py, alongside
this project's other genuine-async httpx.AsyncClient/ASGITransport test
(test_subsystem2_boundary.py) rather than inside a module that also runs
TestClient.websocket_connect tests (advisor review, this unit): that
websocket helper runs its own thread with its own event loop portal, and a
pytest-asyncio test sharing a module with it produced a one-off
CancelledError flake on a full-suite run. This file has no WebSocket tests
in it, so pytest-asyncio's loop teardown has nothing of that kind to
interact with.

Fixtures are self-contained (not imported from tests/api/test_chat_api.py)
per this project's existing tests/integration/ convention - this file owns
its own user/scenario/thread setup and teardown rather than reaching back
into an api-test module."""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from datetime import date
from decimal import Decimal

import httpx
import psycopg
import pytest
import pytest_asyncio
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.auth import User
from app.db.enums import UserRole
from app.db.exception_flags import ExceptionFlag
from app.db.scenario import Scenario
from app.main import create_app
from tests.support.auth import TEST_SESSION_SECRET, make_token

_PRODUCT_ID = "SKU-COR-001"
_WAREHOUSE_ID = "WH-EAST"
_ADMIN_EMAIL = "zztest-chat-attachment-body-size-admin@meadowops.local"
_ANALYST_EMAIL = "zztest-chat-attachment-body-size-analyst@meadowops.local"
_SERVICE_TOKEN = "test-internal-service-token-value-at-least-32-bytes-long"


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "session_secret_key": TEST_SESSION_SECRET,
        "internal_service_token": _SERVICE_TOKEN,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def admin_user_id(db_session: Session) -> Generator[str, None, None]:
    db_session.execute(delete(User).where(User.email == _ADMIN_EMAIL))
    db_session.commit()
    user = User(email=_ADMIN_EMAIL, password_hash="x", role=UserRole.ADMIN, is_active=True)
    db_session.add(user)
    db_session.commit()
    yield str(user.id)
    db_session.execute(delete(User).where(User.email == _ADMIN_EMAIL))
    db_session.commit()


@pytest.fixture
def analyst_user_id(db_session: Session) -> Generator[str, None, None]:
    db_session.execute(delete(User).where(User.email == _ANALYST_EMAIL))
    db_session.commit()
    user = User(email=_ANALYST_EMAIL, password_hash="x", role=UserRole.ANALYST, is_active=True)
    db_session.add(user)
    db_session.commit()
    yield str(user.id)
    db_session.execute(delete(User).where(User.email == _ANALYST_EMAIL))
    db_session.commit()


@pytest.fixture
def analyst_auth(analyst_user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token('analyst', user_id=analyst_user_id)}"}


@pytest.fixture
def scenario_id(
    db_session: Session, admin_user_id: str, owner_dsn: str
) -> Generator[str, None, None]:
    flag = ExceptionFlag(
        category="low_stock_days_of_supply",
        product_id=_PRODUCT_ID,
        warehouse_id=_WAREHOUSE_ID,
        simulation_date=date(2026, 6, 1),
        first_detected_simulation_date=date(2026, 5, 20),
        measured_value=Decimal("4.00"),
        threshold_value=Decimal("10.00"),
    )
    scenario = Scenario(
        title="zztest chat attachment body-size scenario",
        scenario_type="stakeholder_request",
        competency_cluster="communication",
        difficulty_tier="foundational",
        source="manual",
        ground_truth={},
        created_by=uuid.UUID(admin_user_id),
    )
    db_session.add(flag)
    db_session.add(scenario)
    db_session.commit()
    yield str(scenario.id)
    # Same teardown shape as tests/api/test_chat_api.py's own scenario_id
    # fixture: a fresh autocommit connection so one failed statement can't
    # abort the whole cleanup and leave chat_message_no_delete disabled.
    with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "delete from chat.chat_attachment where thread_id in "
            "(select id from chat.chat_thread where scenario_id = %s)",
            (scenario.id,),
        )
        cur.execute("alter table chat.chat_message disable trigger chat_message_no_delete")
        try:
            cur.execute(
                "delete from chat.chat_message where thread_id in "
                "(select id from chat.chat_thread where scenario_id = %s)",
                (scenario.id,),
            )
        finally:
            cur.execute("alter table chat.chat_message enable trigger chat_message_no_delete")
        cur.execute("delete from chat.chat_thread where scenario_id = %s", (scenario.id,))
        cur.execute("delete from engine.scenario where id = %s", (scenario.id,))
        cur.execute("delete from live.exception_flag where id = %s", (flag.id,))


@pytest_asyncio.fixture
async def thread_id(
    analyst_auth: dict[str, str], admin_user_id: str, scenario_id: str
) -> str:
    app = create_app(settings=_settings())
    admin_auth = {"Authorization": f"Bearer {make_token('admin', user_id=admin_user_id)}"}
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/chat/threads",
                json={"scenario_id": scenario_id, "persona": "cfo"},
                headers=admin_auth,
            )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.asyncio
async def test_a_chunked_body_with_no_content_length_is_still_rejected_early(
    analyst_auth: dict[str, str], thread_id: str
) -> None:
    """Security review, U30c: MaxBodySizeMiddleware's upfront Content-Length
    check can't catch a request that omits Content-Length entirely (real
    chunked transfer - confirmed directly by inspecting the outgoing
    request's own headers below, no `content-length` key present). This is
    the regression test for that path's raise-based backstop in
    `limited_receive`.

    Verified directly (not assumed) what actually happens: the raise DOES
    stop the oversized body from ever being fully received - the property
    that matters - but the response is FastAPI's own generic 400 "There was
    an error parsing the body", not this module's 413. Read in
    fastapi/routing.py: request-body dependency resolution wraps every
    exception except HTTPException/JSONDecodeError into that fixed 400
    before it can reach any handler this app registers, including
    request_body_too_large_handler - see app.core.body_size_limit's own
    module docstring for the full trace."""

    async def chunked_multipart_body():
        boundary = b"----chatapitestboundary"
        yield b"--" + boundary + b"\r\n"
        yield b'Content-Disposition: form-data; name="file"; filename="evidence.jpg"\r\n'
        yield b"Content-Type: image/jpeg\r\n\r\n"
        yield b"\xff" * 70_000
        yield b"\r\n--" + boundary + b"--\r\n"

    app = create_app(settings=_settings(max_attachment_size_bytes=10))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
            request = async_client.build_request(
                "POST",
                f"/api/v1/chat/threads/{thread_id}/attachments",
                content=chunked_multipart_body(),
                headers={
                    "Content-Type": "multipart/form-data; boundary=----chatapitestboundary",
                    **analyst_auth,
                },
            )
            assert "content-length" not in request.headers
            response = await async_client.send(request)
    assert response.status_code == 400
    assert response.json()["detail"] == "There was an error parsing the body"
