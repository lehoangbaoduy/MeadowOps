"""Unit 21a (MEADOWOPS-DOM-014, PRD 6.13, §7, DD-25): chat delivery
infrastructure's REST + WebSocket surface — auth gating (every route
reject_service_role except admin-only thread creation), server-side
sender-identity derivation (the class of forgery bug Unit 20a's
pre-implementation review caught, not repeated here), the WebSocket ticket
handshake, live broadcast delivery, and session-expiry-closes-the-socket
(pre-implementation security review MEDIUM fix).
"""

import os
import time
import uuid
from collections.abc import Generator
from datetime import date
from decimal import Decimal

import psycopg
import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.auth import User
from app.db.enums import UserRole
from app.db.exception_flags import ExceptionFlag
from app.db.scenario import Scenario
from app.main import create_app
from app.services.baseline_data import seed_master_data
from app.services.exception_rule_defaults import seed_exception_rule_thresholds
from tests.support.auth import TEST_SESSION_SECRET, make_token

_PRODUCT_ID = "SKU-COR-001"
_WAREHOUSE_ID = "WH-EAST"
_ADMIN_EMAIL = "zztest-chat-api-admin@meadowops.local"
_ANALYST_EMAIL = "zztest-chat-api-analyst@meadowops.local"
_SERVICE_TOKEN = "test-internal-service-token-value-at-least-32-bytes-long"

_SERVICE_AUTH = {"Authorization": f"Bearer {_SERVICE_TOKEN}"}


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "session_secret_key": TEST_SESSION_SECRET,
        "internal_service_token": _SERVICE_TOKEN,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(create_app(settings=_settings())) as c:
        yield c


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
    seed_master_data(db_session)
    seed_exception_rule_thresholds(db_session)
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
def admin_auth(admin_user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token('admin', user_id=admin_user_id)}"}


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
        title="zztest chat api scenario",
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
    # Every test in this module that creates a chat_thread does so against
    # this one scenario — cleaning up here, in the common ancestor fixture,
    # covers every one of them uniformly rather than requiring each test
    # (or the `thread_id` fixture) to remember its own chat-table teardown.
    #
    # A fresh autocommit psycopg connection, not `db_session` (code review
    # of this unit, MEDIUM): the original version ran this as one
    # multi-statement transaction on `db_session` — if any statement
    # raised, Postgres aborts the whole transaction and every later
    # statement in the sequence (including re-enabling the trigger) fails
    # too, since a failed transaction rejects further commands until
    # rolled back. Autocommit (same pattern tests/infra/
    # test_sandbox_boundary.py already uses for its own DDL-heavy
    # cleanups) makes each statement below its own independent transaction,
    # so a failure partway through can't cascade into leaving
    # chat_message_no_delete disabled on the shared dev database — the one
    # mechanism actually enforcing PRD 6.13/ER-6 immutability.
    with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
        # Unit 21 (MEADOWOPS-DOM-015): chat_thread_read_state (migration
        # 0019) FK-references chat_thread, and this module's new mark-read
        # tests create rows in it — deleted first, or the chat_thread
        # delete below fails with a ForeignKeyViolation, which (an
        # unhandled exception, not caught by the try/finally above, which
        # only wraps the message-trigger dance) aborts this whole teardown
        # early and leaks the scenario/exception_flag rows past it, later
        # blocking an unrelated test's own user-row cleanup with a second,
        # confusing FK violation (found by running the suite after adding
        # this unit's tests — the exact failure mode this fixture's own
        # docstring already warns about for any future FK-owning addition).
        cur.execute(
            "delete from chat.chat_thread_read_state where thread_id in "
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


@pytest.fixture
def thread_id(client: TestClient, admin_auth: dict[str, str], scenario_id: str) -> str:
    response = client.post(
        "/api/v1/chat/threads",
        json={"scenario_id": scenario_id, "persona": "cfo"},
        headers=admin_auth,
    )
    assert response.status_code == 201
    return response.json()["id"]


class TestWsTicketRoute:
    def test_admin_can_mint_a_ticket(self, client: TestClient, admin_auth: dict[str, str]) -> None:
        response = client.post("/api/v1/chat/ws-ticket", headers=admin_auth)
        assert response.status_code == 200
        assert response.json()["ticket"]

    def test_analyst_can_mint_a_ticket(
        self, client: TestClient, analyst_auth: dict[str, str]
    ) -> None:
        response = client.post("/api/v1/chat/ws-ticket", headers=analyst_auth)
        assert response.status_code == 200

    def test_service_credential_is_rejected(self, client: TestClient) -> None:
        response = client.post("/api/v1/chat/ws-ticket", headers=_SERVICE_AUTH)
        assert response.status_code == 403

    def test_two_mints_produce_different_tickets(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        first = client.post("/api/v1/chat/ws-ticket", headers=admin_auth).json()["ticket"]
        second = client.post("/api/v1/chat/ws-ticket", headers=admin_auth).json()["ticket"]
        assert first != second

    def test_unauthenticated_request_is_rejected(self, client: TestClient) -> None:
        response = client.post("/api/v1/chat/ws-ticket")
        assert response.status_code == 401


class TestCreateThreadRoute:
    def test_admin_can_create_a_thread(
        self, client: TestClient, admin_auth: dict[str, str], scenario_id: str
    ) -> None:
        response = client.post(
            "/api/v1/chat/threads",
            json={"scenario_id": scenario_id, "persona": "cfo"},
            headers=admin_auth,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["scenario_id"] == scenario_id
        assert body["persona"] == "cfo"

    def test_analyst_cannot_create_a_thread(
        self, client: TestClient, analyst_auth: dict[str, str], scenario_id: str
    ) -> None:
        response = client.post(
            "/api/v1/chat/threads",
            json={"scenario_id": scenario_id, "persona": "cfo"},
            headers=analyst_auth,
        )
        assert response.status_code == 403

    def test_service_credential_cannot_create_a_thread(
        self, client: TestClient, scenario_id: str
    ) -> None:
        response = client.post(
            "/api/v1/chat/threads",
            json={"scenario_id": scenario_id, "persona": "cfo"},
            headers=_SERVICE_AUTH,
        )
        assert response.status_code == 403

    def test_creating_the_same_scenario_persona_pair_twice_returns_the_same_thread(
        self, client: TestClient, admin_auth: dict[str, str], scenario_id: str
    ) -> None:
        first = client.post(
            "/api/v1/chat/threads",
            json={"scenario_id": scenario_id, "persona": "cfo"},
            headers=admin_auth,
        ).json()
        second = client.post(
            "/api/v1/chat/threads",
            json={"scenario_id": scenario_id, "persona": "cfo"},
            headers=admin_auth,
        ).json()
        assert first["id"] == second["id"]

    def test_unknown_scenario_id_returns_404(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        response = client.post(
            "/api/v1/chat/threads",
            json={"scenario_id": str(uuid.uuid4()), "persona": "cfo"},
            headers=admin_auth,
        )
        assert response.status_code == 404


class TestListThreadsRoute:
    def test_analyst_can_list_threads(
        self, client: TestClient, analyst_auth: dict[str, str], thread_id: str
    ) -> None:
        response = client.get("/api/v1/chat/threads", headers=analyst_auth)
        assert response.status_code == 200
        assert thread_id in {t["id"] for t in response.json()}

    def test_service_credential_cannot_list_threads(self, client: TestClient) -> None:
        response = client.get("/api/v1/chat/threads", headers=_SERVICE_AUTH)
        assert response.status_code == 403

    def test_a_thread_with_no_messages_has_zero_unread(
        self, client: TestClient, analyst_auth: dict[str, str], thread_id: str
    ) -> None:
        response = client.get("/api/v1/chat/threads", headers=analyst_auth)
        by_id = {t["id"]: t for t in response.json()}
        assert by_id[thread_id]["unread_count"] == 0

    def test_a_sent_message_is_unread_for_a_viewer_who_never_marked_it_read(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        thread_id: str,
    ) -> None:
        client.post(
            f"/api/v1/chat/threads/{thread_id}/messages",
            json={"body": "opening message"},
            headers=admin_auth,
        )
        response = client.get("/api/v1/chat/threads", headers=analyst_auth)
        by_id = {t["id"]: t for t in response.json()}
        assert by_id[thread_id]["unread_count"] == 1

    def test_marking_a_thread_read_zeroes_unread_for_that_viewer_only(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        thread_id: str,
    ) -> None:
        client.post(
            f"/api/v1/chat/threads/{thread_id}/messages",
            json={"body": "opening message"},
            headers=admin_auth,
        )
        mark_response = client.post(
            f"/api/v1/chat/threads/{thread_id}/read", headers=analyst_auth
        )
        assert mark_response.status_code == 204

        analyst_view = {
            t["id"]: t for t in client.get("/api/v1/chat/threads", headers=analyst_auth).json()
        }
        admin_view = {
            t["id"]: t for t in client.get("/api/v1/chat/threads", headers=admin_auth).json()
        }
        assert analyst_view[thread_id]["unread_count"] == 0
        assert admin_view[thread_id]["unread_count"] == 1

    def test_a_message_sent_after_marking_read_shows_as_unread_again(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        thread_id: str,
    ) -> None:
        """The scenario tests/services/test_chat_service.py's own docstring
        explains it can't cover: real, separately-committed HTTP calls (this
        TestClient does one transaction per request, matching production)
        give the two messages genuinely distinct sent_at values around the
        mark-read call in between, unlike a single shared uncommitted
        transaction where Postgres's now() is frozen at BEGIN."""
        client.post(
            f"/api/v1/chat/threads/{thread_id}/messages",
            json={"body": "seen before read"},
            headers=admin_auth,
        )
        client.post(f"/api/v1/chat/threads/{thread_id}/read", headers=analyst_auth)
        client.post(
            f"/api/v1/chat/threads/{thread_id}/messages",
            json={"body": "arrives after read"},
            headers=admin_auth,
        )
        analyst_view = {
            t["id"]: t for t in client.get("/api/v1/chat/threads", headers=analyst_auth).json()
        }
        assert analyst_view[thread_id]["unread_count"] == 1


class TestMarkThreadReadRoute:
    def test_service_credential_cannot_mark_read(self, client: TestClient, thread_id: str) -> None:
        response = client.post(
            f"/api/v1/chat/threads/{thread_id}/read", headers=_SERVICE_AUTH
        )
        assert response.status_code == 403

    def test_unauthenticated_request_is_rejected(
        self, client: TestClient, thread_id: str
    ) -> None:
        response = client.post(f"/api/v1/chat/threads/{thread_id}/read")
        assert response.status_code == 401

    def test_unknown_thread_id_returns_404(
        self, client: TestClient, analyst_auth: dict[str, str]
    ) -> None:
        response = client.post(
            f"/api/v1/chat/threads/{uuid.uuid4()}/read", headers=analyst_auth
        )
        assert response.status_code == 404

    def test_marking_read_twice_is_not_an_error(
        self, client: TestClient, analyst_auth: dict[str, str], thread_id: str
    ) -> None:
        first = client.post(f"/api/v1/chat/threads/{thread_id}/read", headers=analyst_auth)
        second = client.post(f"/api/v1/chat/threads/{thread_id}/read", headers=analyst_auth)
        assert first.status_code == 204
        assert second.status_code == 204


class TestMessagesRoute:
    def test_analyst_can_send_a_message_and_sender_identity_is_server_derived(
        self, client: TestClient, analyst_auth: dict[str, str], analyst_user_id: str, thread_id: str
    ) -> None:
        """The request body carries no sender field at all — proving the
        response's sender_role/sender_user_id can only have come from the
        caller's own verified session, not anything client-supplied."""
        response = client.post(
            f"/api/v1/chat/threads/{thread_id}/messages",
            json={"body": "Fill rate on SKU-COR-001 has dropped this week."},
            headers=analyst_auth,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["sender_role"] == "analyst"
        assert body["sender_user_id"] == analyst_user_id

    def test_admin_send_is_recorded_as_admin(
        self, client: TestClient, admin_auth: dict[str, str], admin_user_id: str, thread_id: str
    ) -> None:
        response = client.post(
            f"/api/v1/chat/threads/{thread_id}/messages",
            json={"body": "What's the latest on East's service level?"},
            headers=admin_auth,
        )
        assert response.status_code == 201
        assert response.json()["sender_role"] == "admin"
        assert response.json()["sender_user_id"] == admin_user_id

    def test_service_credential_cannot_send_a_message(
        self, client: TestClient, thread_id: str
    ) -> None:
        response = client.post(
            f"/api/v1/chat/threads/{thread_id}/messages",
            json={"body": "hello"},
            headers=_SERVICE_AUTH,
        )
        assert response.status_code == 403

    def test_sending_to_an_unknown_thread_returns_404(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        response = client.post(
            f"/api/v1/chat/threads/{uuid.uuid4()}/messages",
            json={"body": "hello"},
            headers=admin_auth,
        )
        assert response.status_code == 404

    def test_empty_body_is_rejected(
        self, client: TestClient, admin_auth: dict[str, str], thread_id: str
    ) -> None:
        response = client.post(
            f"/api/v1/chat/threads/{thread_id}/messages",
            json={"body": ""},
            headers=admin_auth,
        )
        assert response.status_code == 422

    def test_oversized_body_is_rejected(
        self, client: TestClient, admin_auth: dict[str, str], thread_id: str
    ) -> None:
        response = client.post(
            f"/api/v1/chat/threads/{thread_id}/messages",
            json={"body": "x" * 10_001},
            headers=admin_auth,
        )
        assert response.status_code == 422

    def test_list_messages_returns_sent_messages(
        self, client: TestClient, admin_auth: dict[str, str], thread_id: str
    ) -> None:
        client.post(
            f"/api/v1/chat/threads/{thread_id}/messages",
            json={"body": "first message"},
            headers=admin_auth,
        )
        response = client.get(f"/api/v1/chat/threads/{thread_id}/messages", headers=admin_auth)
        assert response.status_code == 200
        assert any(m["body"] == "first message" for m in response.json())

    def test_service_credential_cannot_list_messages(
        self, client: TestClient, thread_id: str
    ) -> None:
        response = client.get(f"/api/v1/chat/threads/{thread_id}/messages", headers=_SERVICE_AUTH)
        assert response.status_code == 403


class TestWebSocketConnection:
    def test_connecting_without_a_ticket_is_rejected(self, client: TestClient) -> None:
        """Code review of this unit, LOW: a bare `pytest.raises(Exception)`
        would pass equally on an unrelated routing error — tightened to
        confirm this specifically closes with the ticket-rejection code,
        same as the already-specific expired-session test below."""
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/api/v1/chat/ws/chat"):
                pass
        assert exc_info.value.code == 4401

    def test_connecting_with_an_invalid_ticket_is_rejected(self, client: TestClient) -> None:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/api/v1/chat/ws/chat?ticket=not-a-real-ticket"):
                pass
        assert exc_info.value.code == 4401

    def test_connecting_with_a_valid_ticket_succeeds(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        ticket = client.post("/api/v1/chat/ws-ticket", headers=admin_auth).json()["ticket"]
        with client.websocket_connect(f"/api/v1/chat/ws/chat?ticket={ticket}"):
            pass  # connecting at all (no exception) is the assertion

    def test_a_ticket_can_only_be_used_once(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        ticket = client.post("/api/v1/chat/ws-ticket", headers=admin_auth).json()["ticket"]
        with client.websocket_connect(f"/api/v1/chat/ws/chat?ticket={ticket}"):
            pass
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"/api/v1/chat/ws/chat?ticket={ticket}"):
                pass
        assert exc_info.value.code == 4401

    def test_a_connection_closes_when_the_authorizing_session_has_already_expired(
        self, client: TestClient
    ) -> None:
        store = client.app.state.chat_ws_tickets
        ticket = store.mint(user_id="u1", role="admin", session_exp=time.time() - 5)
        with client.websocket_connect(f"/api/v1/chat/ws/chat?ticket={ticket}") as ws:
            data = ws.receive()
            assert data["type"] == "websocket.close"
            assert data["code"] == 4401

    def test_a_sent_message_is_broadcast_to_a_connected_socket(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        thread_id: str,
    ) -> None:
        ticket = client.post("/api/v1/chat/ws-ticket", headers=analyst_auth).json()["ticket"]
        with client.websocket_connect(f"/api/v1/chat/ws/chat?ticket={ticket}") as ws:
            response = client.post(
                f"/api/v1/chat/threads/{thread_id}/messages",
                json={"body": "broadcast me"},
                headers=admin_auth,
            )
            assert response.status_code == 201
            payload = ws.receive_json()
            assert payload["type"] == "chat.message"
            assert payload["thread_id"] == thread_id
            assert payload["body"] == "broadcast me"
            assert payload["sender_role"] == "admin"
