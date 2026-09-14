"""Unit 32 (MEADOWOPS-INFRA-005): end-to-end proof that
Settings.attachment_storage_backend="r2" wires all the way through the real
HTTP routes - get_attachment_storage picks R2AttachmentStorage, the new
run_in_threadpool wrapping in upload_attachment_route doesn't break the
upload-then-claim flow, and get_message_attachment_route's storage.load()
reads back through the same path.

app.main's lifespan constructs a *real* boto3 client (construction alone is
lazy - no network call happens until a request is actually made), pointed
at Settings' r2_account_id/r2_bucket_name. Right after lifespan starts, this
test swaps app.state.r2_client for a moto-backed client with no
`endpoint_url` set, mirroring this project's own established
app.state.claude_client test-substitution pattern (app.main's own comment:
"tests substitute a MockClaudeClient via app.state.claude_client") - moto
does not intercept calls made through a custom endpoint_url (verified
directly: it attempts a real network connection and fails with an SSL
error), so the substitution is what makes this test possible without
touching a real Cloudflare R2 bucket or the network at all.

Lives under tests/integration/, not tests/api/test_chat_api.py, matching
this directory's own genuine-async httpx.AsyncClient/ASGITransport
convention (test_subsystem2_boundary.py, test_chat_attachment_body_size.py)
and its "fixtures are self-contained" precedent - this file owns its own
user/scenario/thread setup rather than reaching into another test module.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from datetime import date
from decimal import Decimal

import boto3
import httpx
import psycopg
import pytest
import pytest_asyncio
from moto import mock_aws
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
_ADMIN_EMAIL = "zztest-chat-attachment-r2-admin@meadowops.local"
_ANALYST_EMAIL = "zztest-chat-attachment-r2-analyst@meadowops.local"
_SERVICE_TOKEN = "test-internal-service-token-value-at-least-32-bytes-long"
_R2_BUCKET = "meadowops-test-attachments"
# Real PNG magic bytes (app.domain.attachment_validation._PNG_MAGIC) plus
# arbitrary trailing bytes - the content-sniffing allowlist checks the
# signature, not that this is a structurally valid PNG.
_PNG_CONTENT = b"\x89PNG\r\n\x1a\n" + b"fake but allowlisted png bytes"

_R2_SETTINGS_FIELDS: dict[str, object] = {
    "attachment_storage_backend": "r2",
    "r2_account_id": "test-account-id",
    "r2_access_key_id": "test-access-key-id",
    "r2_secret_access_key": "test-secret-access-key",
    "r2_bucket_name": _R2_BUCKET,
}


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "session_secret_key": TEST_SESSION_SECRET,
        "internal_service_token": _SERVICE_TOKEN,
        **_R2_SETTINGS_FIELDS,
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
        title="zztest chat attachment r2-backend scenario",
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
async def test_upload_then_download_round_trips_through_the_real_r2_backend(
    analyst_auth: dict[str, str], thread_id: str
) -> None:
    app = create_app(settings=_settings())
    async with app.router.lifespan_context(app):
        # app.state.r2_client already holds a *real* boto3 client at this
        # point (construction is lazy - no network call has happened yet).
        # Swap it for a moto-backed one with no endpoint_url, exactly like
        # this project's existing app.state.claude_client substitution
        # pattern, so the requests below never touch the network.
        with mock_aws():
            moto_client = boto3.client(
                "s3",
                region_name="us-east-1",
                aws_access_key_id="test",
                aws_secret_access_key="test",
            )
            moto_client.create_bucket(Bucket=_R2_BUCKET)
            app.state.r2_client = moto_client

            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                upload_response = await client.post(
                    f"/api/v1/chat/threads/{thread_id}/attachments",
                    files={"file": ("evidence.png", _PNG_CONTENT, "image/png")},
                    headers=analyst_auth,
                )
                assert upload_response.status_code == 201
                attachment_id = upload_response.json()["id"]

                message_response = await client.post(
                    f"/api/v1/chat/threads/{thread_id}/messages",
                    json={"body": "see attached", "attachment_id": attachment_id},
                    headers=analyst_auth,
                )
                assert message_response.status_code == 201
                message_id = message_response.json()["id"]

                download_response = await client.get(
                    f"/api/v1/chat/messages/{message_id}/attachment",
                    headers=analyst_auth,
                )
    assert download_response.status_code == 200
    assert download_response.content == _PNG_CONTENT
    assert download_response.headers["x-content-type-options"] == "nosniff"
