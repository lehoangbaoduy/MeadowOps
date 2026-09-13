"""Unit 21a (MEADOWOPS-DOM-014, PRD 6.13, §7, DD-25): chat delivery
infrastructure's REST + WebSocket surface — auth gating (every route
reject_service_role except admin-only thread creation), server-side
sender-identity derivation (the class of forgery bug Unit 20a's
pre-implementation review caught, not repeated here), the WebSocket ticket
handshake, live broadcast delivery, and session-expiry-closes-the-socket
(pre-implementation security review MEDIUM fix).
"""

import json
import os
import time
import uuid
from collections.abc import Generator
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import psycopg
import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.auth import User
from app.db.chat import ChatThread
from app.db.enums import ChatThreadStatus, ScenarioStatus, UserRole
from app.db.exception_flags import ExceptionFlag
from app.db.scenario import Scenario
from app.domain.claude_client import ClaudeAPIError, ClaudeResponse, MockClaudeClient
from app.main import create_app
from app.services.baseline_data import seed_master_data
from app.services.exception_rule_defaults import seed_exception_rule_thresholds
from app.services.notifications import sweep_thread_deadlines
from app.services.persona_chat import MAX_PUSHBACK_ROUNDS
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
        # Unit 30a (MEADOWOPS-UI-003): chat.notification (migration 0024)
        # FK-references chat_thread too - same predicted gap as the
        # chat_thread_read_state delete just above, an ordinary mutable
        # table with no immutability trigger to dance around.
        cur.execute(
            "delete from chat.notification where thread_id in "
            "(select id from chat.chat_thread where scenario_id = %s)",
            (scenario.id,),
        )
        # Unit 30b (MEADOWOPS-UI-004): chat.chat_thread_draft (migration
        # 0025) FK-references chat_thread too - same predicted gap this
        # fixture's own docstring already warns about.
        cur.execute(
            "delete from chat.chat_thread_draft where thread_id in "
            "(select id from chat.chat_thread where scenario_id = %s)",
            (scenario.id,),
        )
        # Unit 30c (MEADOWOPS-UI-005): chat.chat_attachment (migration
        # 0026) FK-references both chat_thread AND chat_message - deleted
        # here, before the chat_message trigger-disable dance below, or
        # that delete fails with a ForeignKeyViolation the same predicted
        # way this fixture's own docstring already warns about for every
        # later FK-owning addition.
        cur.execute(
            "delete from chat.chat_attachment where thread_id in "
            "(select id from chat.chat_thread where scenario_id = %s)",
            (scenario.id,),
        )
        # Unit 25 (MEADOWOPS-DOM-019): exactly the same class of gap this
        # fixture's own docstring predicted - engine.evaluation FK-
        # references chat_thread too, and this module's new
        # TestCompleteThreadRoute tests create rows in it via the real
        # /complete route. Deleted first (before chat_thread), same
        # immutability-trigger-disable dance as chat_message below.
        cur.execute("alter table engine.evaluation disable trigger evaluation_no_delete")
        try:
            cur.execute(
                "delete from engine.evaluation where thread_id in "
                "(select id from chat.chat_thread where scenario_id = %s)",
                (scenario.id,),
            )
        finally:
            cur.execute("alter table engine.evaluation enable trigger evaluation_no_delete")
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


@pytest.fixture
def rich_scenario_id(db_session: Session, scenario_id: str) -> str:
    """Unit 23: scenario_id's own fixture seeds `ground_truth={}` — fine for
    the delivery-substrate tests above, but the persona-chat suggestion/
    sufficiency-check routes below need a real ground_truth (known_cause,
    evidence, and the grading-only fields the redaction tests assert never
    leak)."""
    scenario = db_session.get(Scenario, uuid.UUID(scenario_id))
    scenario.ground_truth = {
        "known_cause": "Reorder point misconfigured for SKU-COR-001",
        "evidence": {"product_id": _PRODUCT_ID, "warehouse_id": _WAREHOUSE_ID, "on_hand": 12},
        "supporting_signals": ["SECRET-SIGNAL"],
        "distractors": ["SECRET-DISTRACTOR"],
        "expected_considerations": ["SECRET-CONSIDERATION"],
        "acceptable_conclusions": ["SECRET-CONCLUSION-ok"],
        "unacceptable_conclusions": ["SECRET-CONCLUSION-bad"],
        "uncertainty": "SECRET-UNCERTAINTY",
    }
    db_session.commit()
    return scenario_id


@pytest.fixture
def rich_thread_id(client: TestClient, admin_auth: dict[str, str], rich_scenario_id: str) -> str:
    response = client.post(
        "/api/v1/chat/threads",
        json={"scenario_id": rich_scenario_id, "persona": "cfo"},
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

    def test_a_builder_message_sets_deadline_at_and_is_overdue_stays_false(
        self, client: TestClient, admin_auth: dict[str, str], thread_id: str
    ) -> None:
        client.post(
            f"/api/v1/chat/threads/{thread_id}/messages",
            json={"body": "VP wants a status update"},
            headers=admin_auth,
        )
        by_id = {
            t["id"]: t for t in client.get("/api/v1/chat/threads", headers=admin_auth).json()
        }
        assert by_id[thread_id]["deadline_at"] is not None
        assert by_id[thread_id]["is_overdue"] is False

    def test_a_past_deadline_shows_as_overdue(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        db_session: Session,
        thread_id: str,
    ) -> None:
        client.post(
            f"/api/v1/chat/threads/{thread_id}/messages",
            json={"body": "VP wants a status update"},
            headers=admin_auth,
        )
        thread = db_session.get(ChatThread, uuid.UUID(thread_id))
        thread.deadline_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db_session.commit()

        by_id = {
            t["id"]: t for t in client.get("/api/v1/chat/threads", headers=admin_auth).json()
        }
        assert by_id[thread_id]["is_overdue"] is True

    def test_chat_response_window_days_setting_is_threaded_through_to_the_deadline(
        self, admin_auth: dict[str, str], thread_id: str
    ) -> None:
        """Code review (this unit): Settings.chat_response_window_days
        defaults to 4, same as app.services.chat.
        DEFAULT_RESPONSE_WINDOW_DAYS, so a test that only asserts
        deadline_at is not None can't tell whether create_message_route
        actually reads the setting or the send_message default is doing
        all the work. Overriding it to a non-default value pins the
        wiring at app/api/chat.py's `response_window_days=request.app.
        state.settings.chat_response_window_days` kwarg."""
        with TestClient(create_app(settings=_settings(chat_response_window_days=2))) as client:
            before = datetime.now(timezone.utc)
            client.post(
                f"/api/v1/chat/threads/{thread_id}/messages",
                json={"body": "VP wants a status update"},
                headers=admin_auth,
            )
            by_id = {
                t["id"]: t for t in client.get("/api/v1/chat/threads", headers=admin_auth).json()
            }
            deadline_at = datetime.fromisoformat(by_id[thread_id]["deadline_at"])
            delta = deadline_at - before
            assert timedelta(hours=47) < delta < timedelta(hours=49)


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


class TestSaveDraftRoute:
    """Unit 30b (MEADOWOPS-UI-004, PRD 6.1 'Drafting' bullet, catalog row
    31, B12 follow-on to U30)."""

    def test_service_credential_cannot_save_a_draft(
        self, client: TestClient, thread_id: str
    ) -> None:
        response = client.put(
            f"/api/v1/chat/threads/{thread_id}/draft",
            json={"body": "hello"},
            headers=_SERVICE_AUTH,
        )
        assert response.status_code == 403

    def test_unauthenticated_request_is_rejected(
        self, client: TestClient, thread_id: str
    ) -> None:
        response = client.put(
            f"/api/v1/chat/threads/{thread_id}/draft", json={"body": "hello"}
        )
        assert response.status_code == 401

    def test_unknown_thread_id_returns_404(
        self, client: TestClient, analyst_auth: dict[str, str]
    ) -> None:
        response = client.put(
            f"/api/v1/chat/threads/{uuid.uuid4()}/draft",
            json={"body": "hello"},
            headers=analyst_auth,
        )
        assert response.status_code == 404

    def test_a_saved_draft_shows_up_in_the_threads_list_for_its_owner(
        self, client: TestClient, analyst_auth: dict[str, str], thread_id: str
    ) -> None:
        response = client.put(
            f"/api/v1/chat/threads/{thread_id}/draft",
            json={"body": "still working on this reply"},
            headers=analyst_auth,
        )
        assert response.status_code == 204

        by_id = {
            t["id"]: t for t in client.get("/api/v1/chat/threads", headers=analyst_auth).json()
        }
        assert by_id[thread_id]["draft_body"] == "still working on this reply"

    def test_a_thread_with_no_draft_has_an_empty_draft_body(
        self, client: TestClient, admin_auth: dict[str, str], thread_id: str
    ) -> None:
        by_id = {
            t["id"]: t for t in client.get("/api/v1/chat/threads", headers=admin_auth).json()
        }
        assert by_id[thread_id]["draft_body"] == ""

    def test_a_builders_draft_and_an_analysts_draft_never_collide(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        thread_id: str,
    ) -> None:
        client.put(
            f"/api/v1/chat/threads/{thread_id}/draft",
            json={"body": "Builder's persona draft"},
            headers=admin_auth,
        )
        client.put(
            f"/api/v1/chat/threads/{thread_id}/draft",
            json={"body": "Analyst's reply draft"},
            headers=analyst_auth,
        )
        admin_view = {
            t["id"]: t for t in client.get("/api/v1/chat/threads", headers=admin_auth).json()
        }
        analyst_view = {
            t["id"]: t for t in client.get("/api/v1/chat/threads", headers=analyst_auth).json()
        }
        assert admin_view[thread_id]["draft_body"] == "Builder's persona draft"
        assert analyst_view[thread_id]["draft_body"] == "Analyst's reply draft"

    def test_an_empty_body_clears_a_previously_saved_draft(
        self, client: TestClient, analyst_auth: dict[str, str], thread_id: str
    ) -> None:
        client.put(
            f"/api/v1/chat/threads/{thread_id}/draft",
            json={"body": "never mind"},
            headers=analyst_auth,
        )
        clear_response = client.put(
            f"/api/v1/chat/threads/{thread_id}/draft", json={"body": ""}, headers=analyst_auth
        )
        assert clear_response.status_code == 204

        by_id = {
            t["id"]: t for t in client.get("/api/v1/chat/threads", headers=analyst_auth).json()
        }
        assert by_id[thread_id]["draft_body"] == ""

    def test_a_body_over_the_length_cap_is_rejected(
        self, client: TestClient, analyst_auth: dict[str, str], thread_id: str
    ) -> None:
        response = client.put(
            f"/api/v1/chat/threads/{thread_id}/draft",
            json={"body": "x" * 10_001},
            headers=analyst_auth,
        )
        assert response.status_code == 422

    def test_a_successful_send_clears_the_senders_own_draft(
        self, client: TestClient, admin_auth: dict[str, str], thread_id: str
    ) -> None:
        client.put(
            f"/api/v1/chat/threads/{thread_id}/draft",
            json={"body": "about to send this"},
            headers=admin_auth,
        )
        client.post(
            f"/api/v1/chat/threads/{thread_id}/messages",
            json={"body": "about to send this"},
            headers=admin_auth,
        )
        by_id = {
            t["id"]: t for t in client.get("/api/v1/chat/threads", headers=admin_auth).json()
        }
        assert by_id[thread_id]["draft_body"] == ""


class TestListNotificationsRoute:
    """Unit 30a (MEADOWOPS-UI-003, PRD 6.1, B12): sweep_thread_deadlines
    itself is scheduler-tick-driven (tests/domain/test_scheduler.py,
    tests/services/test_notifications_service.py) - these tests call it
    directly against `db_session`, the same way this module already backdates
    ChatThread.deadline_at directly for TestListThreadsRoute's overdue test,
    then assert on the real REST surface a Builder/Analyst actually sees."""

    def test_a_missed_deadline_produces_a_notification_the_builder_can_list(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        db_session: Session,
        thread_id: str,
    ) -> None:
        client.post(
            f"/api/v1/chat/threads/{thread_id}/messages",
            json={"body": "VP wants a status update"},
            headers=admin_auth,
        )
        thread = db_session.get(ChatThread, uuid.UUID(thread_id))
        thread.deadline_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db_session.commit()
        sweep_thread_deadlines(
            db_session, now=datetime.now(timezone.utc), approaching_within=timedelta(hours=24)
        )
        db_session.commit()

        response = client.get("/api/v1/chat/notifications", headers=admin_auth)
        assert response.status_code == 200
        by_thread = {n["thread_id"]: n for n in response.json()}
        assert by_thread[thread_id]["kind"] == "deadline_missed"
        assert by_thread[thread_id]["read_at"] is None

    def test_the_analyst_does_not_see_the_builders_deadline_missed_notification(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        db_session: Session,
        thread_id: str,
    ) -> None:
        client.post(
            f"/api/v1/chat/threads/{thread_id}/messages",
            json={"body": "VP wants a status update"},
            headers=admin_auth,
        )
        thread = db_session.get(ChatThread, uuid.UUID(thread_id))
        thread.deadline_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db_session.commit()
        sweep_thread_deadlines(
            db_session, now=datetime.now(timezone.utc), approaching_within=timedelta(hours=24)
        )
        db_session.commit()

        response = client.get("/api/v1/chat/notifications", headers=analyst_auth)
        assert response.json() == []

    def test_service_credential_cannot_list_notifications(self, client: TestClient) -> None:
        response = client.get("/api/v1/chat/notifications", headers=_SERVICE_AUTH)
        assert response.status_code == 403

    def test_unauthenticated_request_is_rejected(self, client: TestClient) -> None:
        response = client.get("/api/v1/chat/notifications")
        assert response.status_code == 401


class TestMarkNotificationReadRoute:
    def test_owner_can_mark_their_own_notification_read(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        db_session: Session,
        thread_id: str,
    ) -> None:
        client.post(
            f"/api/v1/chat/threads/{thread_id}/messages",
            json={"body": "VP wants a status update"},
            headers=admin_auth,
        )
        thread = db_session.get(ChatThread, uuid.UUID(thread_id))
        thread.deadline_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db_session.commit()
        sweep_thread_deadlines(
            db_session, now=datetime.now(timezone.utc), approaching_within=timedelta(hours=24)
        )
        db_session.commit()
        notification_id = client.get(
            "/api/v1/chat/notifications", headers=admin_auth
        ).json()[0]["id"]

        response = client.post(
            f"/api/v1/chat/notifications/{notification_id}/read", headers=admin_auth
        )
        assert response.status_code == 204

        listed = client.get("/api/v1/chat/notifications", headers=admin_auth).json()
        assert listed[0]["read_at"] is not None

    def test_unknown_id_returns_404(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        response = client.post(
            f"/api/v1/chat/notifications/{uuid.uuid4()}/read", headers=admin_auth
        )
        assert response.status_code == 404

    def test_marking_someone_elses_notification_returns_404(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        db_session: Session,
        thread_id: str,
    ) -> None:
        client.post(
            f"/api/v1/chat/threads/{thread_id}/messages",
            json={"body": "VP wants a status update"},
            headers=admin_auth,
        )
        thread = db_session.get(ChatThread, uuid.UUID(thread_id))
        thread.deadline_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db_session.commit()
        sweep_thread_deadlines(
            db_session, now=datetime.now(timezone.utc), approaching_within=timedelta(hours=24)
        )
        db_session.commit()
        notification_id = client.get(
            "/api/v1/chat/notifications", headers=admin_auth
        ).json()[0]["id"]

        response = client.post(
            f"/api/v1/chat/notifications/{notification_id}/read", headers=analyst_auth
        )
        assert response.status_code == 404

    def test_service_credential_cannot_mark_read(self, client: TestClient) -> None:
        response = client.post(
            f"/api/v1/chat/notifications/{uuid.uuid4()}/read", headers=_SERVICE_AUTH
        )
        assert response.status_code == 403

    def test_unauthenticated_request_is_rejected(self, client: TestClient) -> None:
        response = client.post(f"/api/v1/chat/notifications/{uuid.uuid4()}/read")
        assert response.status_code == 401


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

    def test_whitespace_only_body_is_rejected(
        self, client: TestClient, admin_auth: dict[str, str], thread_id: str
    ) -> None:
        """PRD 9.2 catalog row 16: min_length=1 alone lets " " through -
        an empty-looking message must still be rejected."""
        response = client.post(
            f"/api/v1/chat/threads/{thread_id}/messages",
            json={"body": "   \n\t  "},
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


_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00rest-of-a-fake-jpeg"


@pytest.fixture
def tiny_cap_client() -> Generator[TestClient, None, None]:
    """Unit 30c (MEADOWOPS-UI-005): a second app instance whose
    max_attachment_size_bytes is small enough to exercise the 413 path
    without uploading a real multi-megabyte fixture file."""
    with TestClient(create_app(settings=_settings(max_attachment_size_bytes=10))) as c:
        yield c


class TestUploadAttachmentRoute:
    """Unit 30c (MEADOWOPS-UI-005, S1-FR-15/PRD 347/380, B12 follow-on to
    U30)."""

    def test_analyst_can_upload_a_valid_jpeg(
        self, client: TestClient, analyst_auth: dict[str, str], thread_id: str
    ) -> None:
        response = client.post(
            f"/api/v1/chat/threads/{thread_id}/attachments",
            files={"file": ("evidence.jpg", _JPEG_BYTES, "image/jpeg")},
            headers=analyst_auth,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["original_filename"] == "evidence.jpg"
        assert body["content_type"] == "image/jpeg"
        assert body["size_bytes"] == len(_JPEG_BYTES)
        assert "storage_key" not in body

    def test_admin_cannot_upload_an_attachment(
        self, client: TestClient, admin_auth: dict[str, str], thread_id: str
    ) -> None:
        """S1-FR-15: file attachments are Analyst-side, not a capability
        either role gets."""
        response = client.post(
            f"/api/v1/chat/threads/{thread_id}/attachments",
            files={"file": ("evidence.jpg", _JPEG_BYTES, "image/jpeg")},
            headers=admin_auth,
        )
        assert response.status_code == 403

    def test_service_credential_cannot_upload_an_attachment(
        self, client: TestClient, thread_id: str
    ) -> None:
        response = client.post(
            f"/api/v1/chat/threads/{thread_id}/attachments",
            files={"file": ("evidence.jpg", _JPEG_BYTES, "image/jpeg")},
            headers=_SERVICE_AUTH,
        )
        assert response.status_code == 403

    def test_unauthenticated_request_is_rejected(
        self, client: TestClient, thread_id: str
    ) -> None:
        response = client.post(
            f"/api/v1/chat/threads/{thread_id}/attachments",
            files={"file": ("evidence.jpg", _JPEG_BYTES, "image/jpeg")},
        )
        assert response.status_code == 401

    def test_unknown_thread_id_returns_404(
        self, client: TestClient, analyst_auth: dict[str, str]
    ) -> None:
        response = client.post(
            f"/api/v1/chat/threads/{uuid.uuid4()}/attachments",
            files={"file": ("evidence.jpg", _JPEG_BYTES, "image/jpeg")},
            headers=analyst_auth,
        )
        assert response.status_code == 404

    def test_oversized_upload_is_rejected(
        self, tiny_cap_client: TestClient, analyst_auth: dict[str, str], thread_id: str
    ) -> None:
        response = tiny_cap_client.post(
            f"/api/v1/chat/threads/{thread_id}/attachments",
            files={"file": ("evidence.jpg", _JPEG_BYTES, "image/jpeg")},
            headers=analyst_auth,
        )
        assert response.status_code == 413
        # Pins this as the *route's* AttachmentTooLargeError 413 (advisor
        # review, this unit) - distinct from the fixed generic message
        # MaxBodySizeMiddleware's own 413 always returns (see the test
        # below), so the two paths stay told apart if the cap or
        # MULTIPART_OVERHEAD_BYTES ever change.
        assert response.json()["detail"] == "attachment exceeds the 10-byte size cap"

    def test_a_body_exceeding_the_middleware_cap_is_rejected_before_parsing(
        self, tiny_cap_client: TestClient, analyst_auth: dict[str, str], thread_id: str
    ) -> None:
        """Security review, this unit: distinct from
        test_oversized_upload_is_rejected above, which exercises the
        route's own file.read(max_size + 1) bound *after* Starlette has
        already parsed the multipart body. This instead sends a body large
        enough to exceed MaxBodySizeMiddleware's own cap (max_attachment_
        size_bytes + MULTIPART_OVERHEAD_BYTES, here ~64KB since
        tiny_cap_client's max_attachment_size_bytes=10) - rejected by the
        middleware's upfront Content-Length check, before routing or form
        parsing ever runs. The two 413s are told apart by response body:
        the middleware's is a fixed generic message, the route's own is
        AttachmentTooLargeError's byte-count-specific one."""
        oversized_content = b"\xff" * 70_000
        response = tiny_cap_client.post(
            f"/api/v1/chat/threads/{thread_id}/attachments",
            files={"file": ("evidence.jpg", oversized_content, "image/jpeg")},
            headers=analyst_auth,
        )
        assert response.status_code == 413
        assert response.json()["detail"] == "request body exceeds the maximum allowed size"
    # The no-Content-Length (real chunked transfer) regression test for
    # MaxBodySizeMiddleware's raise-based backstop used to live here, but
    # moved to tests/integration/test_chat_attachment_body_size.py
    # (advisor review, this unit): sharing a pytest-asyncio test's module
    # with this class's WebSocket tests (TestClient.websocket_connect,
    # which runs its own thread/event-loop portal) produced a one-off
    # CancelledError flake on a full-suite run. See that file's own module
    # docstring for the full trace of the FastAPI-generic-400 behavior it
    # pins.

    def test_content_that_does_not_match_the_declared_type_is_rejected(
        self, client: TestClient, analyst_auth: dict[str, str], thread_id: str
    ) -> None:
        """The classic bypass this unit's magic-byte sniffing guards
        against - an HTML file claiming to be a CSV."""
        response = client.post(
            f"/api/v1/chat/threads/{thread_id}/attachments",
            files={
                "file": (
                    "not-really.csv",
                    b"<html><body>not a spreadsheet</body></html>",
                    "text/csv",
                )
            },
            headers=analyst_auth,
        )
        assert response.status_code == 422

    def test_an_unallowed_content_type_is_rejected(
        self, client: TestClient, analyst_auth: dict[str, str], thread_id: str
    ) -> None:
        response = client.post(
            f"/api/v1/chat/threads/{thread_id}/attachments",
            files={"file": ("payload.exe", b"MZ\x90\x00\x03\x00", "application/x-msdownload")},
            headers=analyst_auth,
        )
        assert response.status_code == 422


class TestGetMessageAttachmentRoute:
    """Unit 30c (MEADOWOPS-UI-005, S1-FR-15/PRD 347/380, B12 follow-on to
    U30)."""

    def _upload_and_send(
        self, client: TestClient, analyst_auth: dict[str, str], thread_id: str
    ) -> str:
        upload = client.post(
            f"/api/v1/chat/threads/{thread_id}/attachments",
            files={"file": ("evidence.jpg", _JPEG_BYTES, "image/jpeg")},
            headers=analyst_auth,
        )
        assert upload.status_code == 201
        attachment_id = upload.json()["id"]
        message = client.post(
            f"/api/v1/chat/threads/{thread_id}/messages",
            json={"body": "see attached", "attachment_id": attachment_id},
            headers=analyst_auth,
        )
        assert message.status_code == 201
        return message.json()["id"]

    def test_the_uploader_can_download_the_attachment_bytes(
        self, client: TestClient, analyst_auth: dict[str, str], thread_id: str
    ) -> None:
        message_id = self._upload_and_send(client, analyst_auth, thread_id)
        response = client.get(
            f"/api/v1/chat/messages/{message_id}/attachment", headers=analyst_auth
        )
        assert response.status_code == 200
        assert response.content == _JPEG_BYTES
        assert response.headers["content-type"] == "image/jpeg"

    def test_the_other_role_can_also_download_it(
        self,
        client: TestClient,
        analyst_auth: dict[str, str],
        admin_auth: dict[str, str],
        thread_id: str,
    ) -> None:
        """PRD 380: 'served only to the two authenticated roles on the
        owning thread' - both roles, not upload-only-visible-to-uploader."""
        message_id = self._upload_and_send(client, analyst_auth, thread_id)
        response = client.get(
            f"/api/v1/chat/messages/{message_id}/attachment", headers=admin_auth
        )
        assert response.status_code == 200
        assert response.content == _JPEG_BYTES

    def test_response_has_a_content_disposition_attachment_header(
        self, client: TestClient, analyst_auth: dict[str, str], thread_id: str
    ) -> None:
        message_id = self._upload_and_send(client, analyst_auth, thread_id)
        response = client.get(
            f"/api/v1/chat/messages/{message_id}/attachment", headers=analyst_auth
        )
        disposition = response.headers["content-disposition"]
        assert disposition.startswith("attachment;")
        assert "evidence.jpg" in disposition

    def test_a_non_ascii_filename_round_trips_without_crashing(
        self, client: TestClient, analyst_auth: dict[str, str], thread_id: str
    ) -> None:
        """Dual review, this unit (HIGH, caught independently by both the
        code-reviewer and security-reviewer agents): the previous
        Content-Disposition builder only stripped `"`, `\\`, CR, LF and
        passed every other character straight through, including anything
        outside Latin-1 - Starlette encodes response headers as Latin-1
        (`Response.init_headers`), so any CJK/Cyrillic/emoji filename
        crashed this route with an unhandled UnicodeEncodeError, forever
        (the filename is stored once, immutably, at upload time - there is
        no later fix-up path). This is the regression test for the RFC
        6266 dual-parameter fix (_content_disposition_header_value)."""
        upload = client.post(
            f"/api/v1/chat/threads/{thread_id}/attachments",
            files={"file": ("评估.jpg", _JPEG_BYTES, "image/jpeg")},
            headers=analyst_auth,
        )
        assert upload.status_code == 201
        attachment_id = upload.json()["id"]
        message = client.post(
            f"/api/v1/chat/threads/{thread_id}/messages",
            json={"body": "see attached", "attachment_id": attachment_id},
            headers=analyst_auth,
        )
        assert message.status_code == 201
        response = client.get(
            f"/api/v1/chat/messages/{message.json()['id']}/attachment", headers=analyst_auth
        )
        assert response.status_code == 200
        assert response.content == _JPEG_BYTES
        disposition = response.headers["content-disposition"]
        assert disposition.startswith("attachment;")
        # ASCII fallback keeps whatever ASCII survives (here just the
        # extension) rather than falling back to a fixed placeholder name -
        # the real name lives in filename* below for browsers that read it.
        assert 'filename=".jpg"' in disposition
        assert "filename*=UTF-8''%E8%AF%84%E4%BC%B0.jpg" in disposition

    def test_response_has_the_nosniff_header(
        self, client: TestClient, analyst_auth: dict[str, str], thread_id: str
    ) -> None:
        """Advisor review, this unit: the realistic exploit for uploaded
        content isn't server-side execution, it's the browser rendering it
        inline from this origin - this header is what actually closes
        that."""
        message_id = self._upload_and_send(client, analyst_auth, thread_id)
        response = client.get(
            f"/api/v1/chat/messages/{message_id}/attachment", headers=analyst_auth
        )
        assert response.headers["x-content-type-options"] == "nosniff"

    def test_returns_404_for_a_message_with_no_attachment(
        self, client: TestClient, admin_auth: dict[str, str], thread_id: str
    ) -> None:
        message = client.post(
            f"/api/v1/chat/threads/{thread_id}/messages",
            json={"body": "no attachment here"},
            headers=admin_auth,
        )
        message_id = message.json()["id"]
        response = client.get(
            f"/api/v1/chat/messages/{message_id}/attachment", headers=admin_auth
        )
        assert response.status_code == 404

    def test_returns_404_for_an_unknown_message_id(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        response = client.get(
            f"/api/v1/chat/messages/{uuid.uuid4()}/attachment", headers=admin_auth
        )
        assert response.status_code == 404

    def test_service_credential_cannot_download_an_attachment(
        self, client: TestClient, analyst_auth: dict[str, str], thread_id: str
    ) -> None:
        message_id = self._upload_and_send(client, analyst_auth, thread_id)
        response = client.get(
            f"/api/v1/chat/messages/{message_id}/attachment", headers=_SERVICE_AUTH
        )
        assert response.status_code == 403

    def test_unauthenticated_request_is_rejected(
        self, client: TestClient, analyst_auth: dict[str, str], thread_id: str
    ) -> None:
        message_id = self._upload_and_send(client, analyst_auth, thread_id)
        response = client.get(f"/api/v1/chat/messages/{message_id}/attachment")
        assert response.status_code == 401


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


def _post_message(client: TestClient, thread_id: str, auth: dict[str, str], body: str):
    response = client.post(
        f"/api/v1/chat/threads/{thread_id}/messages", json={"body": body}, headers=auth
    )
    assert response.status_code == 201


class TestSuggestPushbackRoute:
    def test_returns_503_when_no_claude_client_is_configured(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        rich_thread_id: str,
    ) -> None:
        _post_message(client, rich_thread_id, admin_auth, "opening")
        _post_message(client, rich_thread_id, analyst_auth, "reply")

        response = client.post(
            f"/api/v1/chat/threads/{rich_thread_id}/suggest-pushback",
            json={"attitude": "neutral"},
            headers=admin_auth,
        )

        assert response.status_code == 503

    def test_analyst_cannot_call_this_route(
        self, client: TestClient, analyst_auth: dict[str, str], rich_thread_id: str
    ) -> None:
        # Builder-only (require_admin, not reject_service_role) - the
        # ground truth must never reach the Analyst role.
        response = client.post(
            f"/api/v1/chat/threads/{rich_thread_id}/suggest-pushback",
            json={"attitude": "neutral"},
            headers=analyst_auth,
        )

        assert response.status_code == 403

    def test_builder_gets_a_suggested_message_once_configured(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        rich_thread_id: str,
    ) -> None:
        _post_message(client, rich_thread_id, admin_auth, "What's driving the stockout?")
        _post_message(client, rich_thread_id, analyst_auth, "I think the reorder point is fine.")
        client.app.state.claude_client = MockClaudeClient(
            script=[ClaudeResponse(content="Skeptical reply.")]
        )

        response = client.post(
            f"/api/v1/chat/threads/{rich_thread_id}/suggest-pushback",
            json={"attitude": "skeptical"},
            headers=admin_auth,
        )

        assert response.status_code == 200
        assert response.json()["suggested_message"] == "Skeptical reply."

    def test_returns_409_when_no_analyst_message_exists_yet(
        self, client: TestClient, admin_auth: dict[str, str], rich_thread_id: str
    ) -> None:
        _post_message(client, rich_thread_id, admin_auth, "opening only")
        client.app.state.claude_client = MockClaudeClient(script=[ClaudeResponse(content="unused")])

        response = client.post(
            f"/api/v1/chat/threads/{rich_thread_id}/suggest-pushback",
            json={"attitude": "neutral"},
            headers=admin_auth,
        )

        assert response.status_code == 409

    def test_returns_404_for_an_unknown_thread(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        client.app.state.claude_client = MockClaudeClient(script=[ClaudeResponse(content="unused")])

        response = client.post(
            f"/api/v1/chat/threads/{uuid.uuid4()}/suggest-pushback",
            json={"attitude": "neutral"},
            headers=admin_auth,
        )

        assert response.status_code == 404

    def test_returns_409_once_the_maximum_pushback_rounds_is_reached(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        rich_thread_id: str,
    ) -> None:
        """PRD 9.2 catalog row 17: the pushback loop must conclude
        gracefully rather than hang indefinitely."""
        for round_number in range(MAX_PUSHBACK_ROUNDS):
            _post_message(client, rich_thread_id, admin_auth, f"pushback {round_number}")
            _post_message(client, rich_thread_id, analyst_auth, f"reply {round_number}")
        client.app.state.claude_client = MockClaudeClient(script=[ClaudeResponse(content="unused")])

        response = client.post(
            f"/api/v1/chat/threads/{rich_thread_id}/suggest-pushback",
            json={"attitude": "neutral"},
            headers=admin_auth,
        )

        assert response.status_code == 409

    def test_returns_502_when_generation_fails_after_retry(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        rich_thread_id: str,
    ) -> None:
        _post_message(client, rich_thread_id, admin_auth, "opening")
        _post_message(client, rich_thread_id, analyst_auth, "reply")
        client.app.state.claude_client = MockClaudeClient(
            script=[ClaudeAPIError("boom"), ClaudeAPIError("boom again")]
        )

        response = client.post(
            f"/api/v1/chat/threads/{rich_thread_id}/suggest-pushback",
            json={"attitude": "neutral"},
            headers=admin_auth,
        )

        assert response.status_code == 502

    def test_rejects_an_invalid_attitude_value(
        self, client: TestClient, admin_auth: dict[str, str], rich_thread_id: str
    ) -> None:
        response = client.post(
            f"/api/v1/chat/threads/{rich_thread_id}/suggest-pushback",
            json={"attitude": "angry"},
            headers=admin_auth,
        )

        assert response.status_code == 422

    def test_the_suggestion_does_not_leak_a_grading_field(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        rich_thread_id: str,
    ) -> None:
        # End-to-end version of app.domain.persona_chat's own redaction
        # test - the MockClaudeClient echoes back whatever the prompt
        # contained, so this proves the redaction survives the full
        # route -> service -> domain call chain, not just the domain layer
        # in isolation.
        _post_message(client, rich_thread_id, admin_auth, "What's driving the stockout?")
        _post_message(client, rich_thread_id, analyst_auth, "I think the reorder point is fine.")

        class _EchoClient:
            def __init__(self) -> None:
                self.call_log: list[dict] = []

            def create_message(self, *, model, system, messages, max_tokens):
                self.call_log.append({"messages": messages})
                return ClaudeResponse(content=messages[0]["content"])

        client.app.state.claude_client = _EchoClient()

        response = client.post(
            f"/api/v1/chat/threads/{rich_thread_id}/suggest-pushback",
            json={"attitude": "neutral"},
            headers=admin_auth,
        )

        assert response.status_code == 200
        suggested = response.json()["suggested_message"]
        for marker in ("SECRET-SIGNAL", "SECRET-DISTRACTOR", "SECRET-CONSIDERATION", "SECRET-CONCLUSION", "SECRET-UNCERTAINTY"):
            assert marker not in suggested


class TestSufficiencyCheckRoute:
    def test_returns_503_when_no_claude_client_is_configured(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        rich_thread_id: str,
    ) -> None:
        _post_message(client, rich_thread_id, admin_auth, "opening")
        _post_message(client, rich_thread_id, analyst_auth, "reply")

        response = client.post(
            f"/api/v1/chat/threads/{rich_thread_id}/sufficiency-check", headers=admin_auth
        )

        assert response.status_code == 503

    def test_analyst_cannot_call_this_route(
        self, client: TestClient, analyst_auth: dict[str, str], rich_thread_id: str
    ) -> None:
        response = client.post(
            f"/api/v1/chat/threads/{rich_thread_id}/sufficiency-check", headers=analyst_auth
        )

        assert response.status_code == 403

    def test_builder_gets_a_verdict_once_configured(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        rich_thread_id: str,
    ) -> None:
        _post_message(client, rich_thread_id, admin_auth, "What's driving the stockout?")
        _post_message(client, rich_thread_id, analyst_auth, "I think the reorder point is fine.")
        payload = {"verdict": "insufficient", "suggested_pushback": "But what about lead time?"}
        client.app.state.claude_client = MockClaudeClient(
            script=[ClaudeResponse(content=json.dumps(payload))]
        )

        response = client.post(
            f"/api/v1/chat/threads/{rich_thread_id}/sufficiency-check", headers=admin_auth
        )

        assert response.status_code == 200
        assert response.json() == payload

    def test_returns_409_when_no_analyst_message_exists_yet(
        self, client: TestClient, admin_auth: dict[str, str], rich_thread_id: str
    ) -> None:
        _post_message(client, rich_thread_id, admin_auth, "opening only")
        client.app.state.claude_client = MockClaudeClient(script=[ClaudeResponse(content="unused")])

        response = client.post(
            f"/api/v1/chat/threads/{rich_thread_id}/sufficiency-check", headers=admin_auth
        )

        assert response.status_code == 409

    def test_returns_404_for_an_unknown_thread(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        client.app.state.claude_client = MockClaudeClient(script=[ClaudeResponse(content="unused")])

        response = client.post(
            f"/api/v1/chat/threads/{uuid.uuid4()}/sufficiency-check", headers=admin_auth
        )

        assert response.status_code == 404

    def test_returns_502_when_the_check_fails_after_retry(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        rich_thread_id: str,
    ) -> None:
        _post_message(client, rich_thread_id, admin_auth, "opening")
        _post_message(client, rich_thread_id, analyst_auth, "reply")
        client.app.state.claude_client = MockClaudeClient(
            script=[ClaudeAPIError("boom"), ClaudeAPIError("boom again")]
        )

        response = client.post(
            f"/api/v1/chat/threads/{rich_thread_id}/sufficiency-check", headers=admin_auth
        )

        assert response.status_code == 502


_VALID_EVALUATION_PAYLOAD = {
    "strengths": "Correctly identified the reorder point issue.",
    "gaps": "Did not quantify the cost impact.",
    "evidence": "Cited the on-hand count and lead time signal.",
    "senior_analyst_pushback": "What would you check next if wrong?",
    "final_verdict": "Solid investigation, minor gaps.",
    "suggested_next_skill_focus": "Quantifying financial impact.",
    "difficulty_recommendation": "standard",
}


class TestCompleteThreadRoute:
    def test_returns_503_when_no_claude_client_is_configured(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        rich_thread_id: str,
    ) -> None:
        _post_message(client, rich_thread_id, admin_auth, "opening")
        _post_message(client, rich_thread_id, analyst_auth, "reply")

        response = client.post(
            f"/api/v1/chat/threads/{rich_thread_id}/complete", headers=admin_auth
        )

        assert response.status_code == 503

    def test_analyst_cannot_call_this_route(
        self, client: TestClient, analyst_auth: dict[str, str], rich_thread_id: str
    ) -> None:
        response = client.post(
            f"/api/v1/chat/threads/{rich_thread_id}/complete", headers=analyst_auth
        )

        assert response.status_code == 403

    def test_builder_gets_a_draft_evaluation_once_configured(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        rich_thread_id: str,
    ) -> None:
        _post_message(client, rich_thread_id, admin_auth, "What's driving the stockout?")
        _post_message(client, rich_thread_id, analyst_auth, "I think the reorder point is fine.")
        client.app.state.claude_client = MockClaudeClient(
            script=[ClaudeResponse(content=json.dumps(_VALID_EVALUATION_PAYLOAD))]
        )

        response = client.post(
            f"/api/v1/chat/threads/{rich_thread_id}/complete", headers=admin_auth
        )

        assert response.status_code == 200
        body = response.json()
        assert body["difficulty_recommendation"] == "standard"
        assert body["thread_id"] == rich_thread_id

    def test_returns_409_when_the_latest_message_is_not_from_the_analyst(
        self, client: TestClient, admin_auth: dict[str, str], rich_thread_id: str
    ) -> None:
        _post_message(client, rich_thread_id, admin_auth, "opening only")
        client.app.state.claude_client = MockClaudeClient(
            script=[ClaudeResponse(content=json.dumps(_VALID_EVALUATION_PAYLOAD))]
        )

        response = client.post(
            f"/api/v1/chat/threads/{rich_thread_id}/complete", headers=admin_auth
        )

        assert response.status_code == 409

    def test_returns_409_when_the_thread_is_already_completed(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        rich_thread_id: str,
    ) -> None:
        _post_message(client, rich_thread_id, admin_auth, "opening")
        _post_message(client, rich_thread_id, analyst_auth, "reply")
        client.app.state.claude_client = MockClaudeClient(
            script=[ClaudeResponse(content=json.dumps(_VALID_EVALUATION_PAYLOAD))]
        )
        client.post(f"/api/v1/chat/threads/{rich_thread_id}/complete", headers=admin_auth)
        client.app.state.claude_client = MockClaudeClient(
            script=[ClaudeResponse(content=json.dumps(_VALID_EVALUATION_PAYLOAD))]
        )

        response = client.post(
            f"/api/v1/chat/threads/{rich_thread_id}/complete", headers=admin_auth
        )

        assert response.status_code == 409

    def test_returns_404_for_an_unknown_thread(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        client.app.state.claude_client = MockClaudeClient(
            script=[ClaudeResponse(content=json.dumps(_VALID_EVALUATION_PAYLOAD))]
        )

        response = client.post(
            f"/api/v1/chat/threads/{uuid.uuid4()}/complete", headers=admin_auth
        )

        assert response.status_code == 404

    def test_returns_409_when_the_scenario_has_been_cancelled(
        self,
        client: TestClient,
        db_session: Session,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        rich_scenario_id: str,
        rich_thread_id: str,
    ) -> None:
        # Advisor review: engine.evaluation rows are permanently immutable
        # (migration 0020's trigger), so a cancelled scenario's thread must
        # be refused here rather than allowed to write one that can never
        # be retracted afterward.
        _post_message(client, rich_thread_id, admin_auth, "opening")
        _post_message(client, rich_thread_id, analyst_auth, "reply")
        scenario = db_session.get(Scenario, uuid.UUID(rich_scenario_id))
        scenario.status = ScenarioStatus.CANCELLED
        db_session.commit()
        client.app.state.claude_client = MockClaudeClient(
            script=[ClaudeResponse(content=json.dumps(_VALID_EVALUATION_PAYLOAD))]
        )

        response = client.post(
            f"/api/v1/chat/threads/{rich_thread_id}/complete", headers=admin_auth
        )

        assert response.status_code == 409

    def test_returns_502_when_generation_fails_after_retry(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        rich_thread_id: str,
    ) -> None:
        _post_message(client, rich_thread_id, admin_auth, "opening")
        _post_message(client, rich_thread_id, analyst_auth, "reply")
        client.app.state.claude_client = MockClaudeClient(
            script=[ClaudeAPIError("boom"), ClaudeAPIError("boom again")]
        )

        response = client.post(
            f"/api/v1/chat/threads/{rich_thread_id}/complete", headers=admin_auth
        )

        assert response.status_code == 502

    def test_a_failed_completion_can_be_retried_and_succeed(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        rich_thread_id: str,
    ) -> None:
        # Proves the deliberate "no persisted stuck state" design
        # (app.db.enums.ChatThreadStatus's own docstring) end-to-end - a
        # failed attempt must not block a subsequent successful one.
        _post_message(client, rich_thread_id, admin_auth, "opening")
        _post_message(client, rich_thread_id, analyst_auth, "reply")
        client.app.state.claude_client = MockClaudeClient(
            script=[ClaudeAPIError("boom"), ClaudeAPIError("boom again")]
        )
        failed = client.post(
            f"/api/v1/chat/threads/{rich_thread_id}/complete", headers=admin_auth
        )
        assert failed.status_code == 502

        client.app.state.claude_client = MockClaudeClient(
            script=[ClaudeResponse(content=json.dumps(_VALID_EVALUATION_PAYLOAD))]
        )
        retried = client.post(
            f"/api/v1/chat/threads/{rich_thread_id}/complete", headers=admin_auth
        )
        assert retried.status_code == 200

    def test_a_concurrent_double_complete_returns_409_not_500(
        self,
        client: TestClient,
        db_session: Session,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        rich_thread_id: str,
    ) -> None:
        # Code review, HIGH: Evaluation.thread_id's unique constraint is
        # the actual backstop against two concurrent /complete calls both
        # passing the in-memory ThreadAlreadyCompletedError check before
        # either commits. Simulated here (rather than real concurrency)
        # by resetting the thread back to OPEN after a first successful
        # completion, then completing it again - the second call's
        # in-memory check now passes, so only the DB-level unique
        # constraint stops a second Evaluation row from being inserted.
        _post_message(client, rich_thread_id, admin_auth, "opening")
        _post_message(client, rich_thread_id, analyst_auth, "reply")
        client.app.state.claude_client = MockClaudeClient(
            script=[ClaudeResponse(content=json.dumps(_VALID_EVALUATION_PAYLOAD))]
        )
        first = client.post(
            f"/api/v1/chat/threads/{rich_thread_id}/complete", headers=admin_auth
        )
        assert first.status_code == 200

        thread = db_session.get(ChatThread, uuid.UUID(rich_thread_id))
        thread.status = ChatThreadStatus.OPEN
        db_session.commit()

        client.app.state.claude_client = MockClaudeClient(
            script=[ClaudeResponse(content=json.dumps(_VALID_EVALUATION_PAYLOAD))]
        )
        second = client.post(
            f"/api/v1/chat/threads/{rich_thread_id}/complete", headers=admin_auth
        )
        assert second.status_code == 409
