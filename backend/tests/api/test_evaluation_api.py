"""Unit 25 (MEADOWOPS-DOM-019, PRD 6.7/6.8/ER-5): read-only evaluation
routes - every route is admin_only (ER-5: hidden from the Analyst during
normal use), unlike Unit 24's ledger reads.
"""

import json
import os
import uuid
from collections.abc import Generator
from datetime import date
from decimal import Decimal

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.auth import User
from app.db.enums import UserRole
from app.db.exception_flags import ExceptionFlag
from app.db.scenario import Scenario
from app.domain.claude_client import ClaudeResponse, MockClaudeClient
from app.main import create_app
from tests.support.auth import TEST_SESSION_SECRET, make_token

_PRODUCT_ID = "SKU-COR-001"
_WAREHOUSE_ID = "WH-EAST"
_ADMIN_EMAIL = "zztest-evaluation-api-admin@meadowops.local"
_ANALYST_EMAIL = "zztest-evaluation-api-analyst@meadowops.local"
_SERVICE_TOKEN = "test-internal-service-token-value-at-least-32-bytes-long"

_VALID_EVALUATION_PAYLOAD = {
    "strengths": "Correctly identified the reorder point issue.",
    "gaps": "Did not quantify the cost impact.",
    "evidence": "Cited the on-hand count and lead time signal.",
    "senior_analyst_pushback": "What would you check next if wrong?",
    "final_verdict": "Solid investigation, minor gaps.",
    "suggested_next_skill_focus": "Quantifying financial impact.",
    "difficulty_recommendation": "standard",
}


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
        title="zztest evaluation api scenario",
        scenario_type="stakeholder_request",
        competency_cluster="communication",
        difficulty_tier="foundational",
        source="manual",
        ground_truth={
            "known_cause": "Reorder point misconfigured for SKU-COR-001",
            "evidence": {"product_id": _PRODUCT_ID, "warehouse_id": _WAREHOUSE_ID, "on_hand": 12},
            "acceptable_conclusions": ["raise the reorder point"],
            "unacceptable_conclusions": ["blame the supplier"],
            "uncertainty": "moderate confidence",
        },
        created_by=uuid.UUID(admin_user_id),
    )
    db_session.add(flag)
    db_session.add(scenario)
    db_session.commit()
    yield str(scenario.id)
    # Same teardown ordering/autocommit reasoning as tests/api/
    # test_chat_api.py's own scenario_id fixture - duplicated rather than
    # imported, this project's established per-test-file convention.
    with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "delete from chat.chat_thread_read_state where thread_id in "
            "(select id from chat.chat_thread where scenario_id = %s)",
            (scenario.id,),
        )
        # Unit 26 (MEADOWOPS-DOM-020): engine.human_review FK-references
        # engine.evaluation, and TestHumanReviewRoutes below creates rows in
        # it via the real /human-review route - exactly the class of gap
        # this fixture's own precedent (app.db.evaluation's FK addition in
        # Unit 25) already warned about. Deleted first, before evaluation.
        cur.execute("alter table engine.human_review disable trigger human_review_no_delete")
        try:
            cur.execute(
                "delete from engine.human_review where evaluation_id in "
                "(select id from engine.evaluation where thread_id in "
                "(select id from chat.chat_thread where scenario_id = %s))",
                (scenario.id,),
            )
        finally:
            cur.execute("alter table engine.human_review enable trigger human_review_no_delete")
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


def _post_message(client: TestClient, thread_id: str, auth: dict[str, str], body: str):
    return client.post(
        f"/api/v1/chat/threads/{thread_id}/messages", json={"body": body}, headers=auth
    )


def _complete_thread(client: TestClient, thread_id: str, admin_auth: dict[str, str]) -> None:
    client.app.state.claude_client = MockClaudeClient(
        script=[ClaudeResponse(content=json.dumps(_VALID_EVALUATION_PAYLOAD))]
    )
    response = client.post(f"/api/v1/chat/threads/{thread_id}/complete", headers=admin_auth)
    assert response.status_code == 200, response.text


class TestGetThreadEvaluationRoute:
    def test_requires_auth(self, client: TestClient, thread_id: str) -> None:
        response = client.get(f"/api/v1/evaluations/threads/{thread_id}")
        assert response.status_code == 401

    def test_forbidden_for_analyst(
        self, client: TestClient, analyst_auth: dict[str, str], thread_id: str
    ) -> None:
        response = client.get(f"/api/v1/evaluations/threads/{thread_id}", headers=analyst_auth)
        assert response.status_code == 403

    def test_returns_404_when_the_thread_has_no_evaluation_yet(
        self, client: TestClient, admin_auth: dict[str, str], thread_id: str
    ) -> None:
        response = client.get(f"/api/v1/evaluations/threads/{thread_id}", headers=admin_auth)
        assert response.status_code == 404

    def test_returns_404_for_an_unknown_thread(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        response = client.get(
            f"/api/v1/evaluations/threads/{uuid.uuid4()}", headers=admin_auth
        )
        assert response.status_code == 404

    def test_returns_the_evaluation_once_the_thread_is_completed(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        thread_id: str,
    ) -> None:
        _post_message(client, thread_id, admin_auth, "opening")
        _post_message(client, thread_id, analyst_auth, "reply")
        _complete_thread(client, thread_id, admin_auth)

        response = client.get(f"/api/v1/evaluations/threads/{thread_id}", headers=admin_auth)

        assert response.status_code == 200
        body = response.json()
        assert body["thread_id"] == thread_id
        assert body["difficulty_recommendation"] == "standard"
        assert "raw_response" not in body


class TestClusterDifficultyRecommendationRoute:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.get("/api/v1/evaluations/clusters/communication/difficulty-recommendation")
        assert response.status_code == 401

    def test_forbidden_for_analyst(self, client: TestClient, analyst_auth: dict[str, str]) -> None:
        response = client.get(
            "/api/v1/evaluations/clusters/communication/difficulty-recommendation",
            headers=analyst_auth,
        )
        assert response.status_code == 403

    def test_holds_with_insufficient_evidence(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        response = client.get(
            "/api/v1/evaluations/clusters/communication/difficulty-recommendation",
            headers=admin_auth,
        )
        assert response.status_code == 200
        assert response.json() == {"cluster": "communication", "recommendation": "hold"}

    def test_rejects_an_invalid_cluster(self, client: TestClient, admin_auth: dict[str, str]) -> None:
        response = client.get(
            "/api/v1/evaluations/clusters/not-a-real-cluster/difficulty-recommendation",
            headers=admin_auth,
        )
        assert response.status_code == 422


class TestHumanReviewRoutes:
    def test_requires_auth_to_record(self, client: TestClient, thread_id: str) -> None:
        response = client.post(f"/api/v1/evaluations/threads/{thread_id}/human-review", json={})
        assert response.status_code == 401

    def test_forbidden_for_analyst(
        self, client: TestClient, analyst_auth: dict[str, str], thread_id: str
    ) -> None:
        response = client.post(
            f"/api/v1/evaluations/threads/{thread_id}/human-review",
            json={"reviewer_name": "r", "verdict": "agree", "tier_assessment_notes": "n"},
            headers=analyst_auth,
        )
        assert response.status_code == 403

    def test_returns_404_when_the_thread_has_no_evaluation_yet(
        self, client: TestClient, admin_auth: dict[str, str], thread_id: str
    ) -> None:
        response = client.post(
            f"/api/v1/evaluations/threads/{thread_id}/human-review",
            json={"reviewer_name": "r", "verdict": "agree", "tier_assessment_notes": "n"},
            headers=admin_auth,
        )
        assert response.status_code == 404

    def test_records_an_agree_verdict(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        thread_id: str,
        admin_user_id: str,
        owner_dsn: str,
    ) -> None:
        _post_message(client, thread_id, admin_auth, "opening")
        _post_message(client, thread_id, analyst_auth, "reply")
        _complete_thread(client, thread_id, admin_auth)

        response = client.post(
            f"/api/v1/evaluations/threads/{thread_id}/human-review",
            json={
                "reviewer_name": "Prof. Rivera",
                "verdict": "agree",
                "tier_assessment_notes": "Standard tier matches demonstrated level.",
            },
            headers=admin_auth,
        )

        assert response.status_code == 201
        body = response.json()
        assert body["verdict"] == "agree"
        assert body["overridden_recommendation"] is None
        # Security review of this unit: the route must populate
        # submitted_by_user_id from the authenticated identity, not leave it
        # unwired - checked against the DB row directly since
        # HumanReviewRead deliberately doesn't expose this column.
        with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "select submitted_by_user_id from engine.human_review where id = %s",
                (body["id"],),
            )
            (submitted_by_user_id,) = cur.fetchone()
        assert str(submitted_by_user_id) == admin_user_id

    def test_records_an_override_verdict(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        thread_id: str,
    ) -> None:
        _post_message(client, thread_id, admin_auth, "opening")
        _post_message(client, thread_id, analyst_auth, "reply")
        _complete_thread(client, thread_id, admin_auth)

        response = client.post(
            f"/api/v1/evaluations/threads/{thread_id}/human-review",
            json={
                "reviewer_name": "Prof. Rivera",
                "verdict": "override",
                "tier_assessment_notes": "Evidence supports a stretch call.",
                "overridden_recommendation": "stretch",
            },
            headers=admin_auth,
        )

        assert response.status_code == 201
        assert response.json()["overridden_recommendation"] == "stretch"

    def test_rejects_agree_with_an_overridden_recommendation(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        thread_id: str,
    ) -> None:
        _post_message(client, thread_id, admin_auth, "opening")
        _post_message(client, thread_id, analyst_auth, "reply")
        _complete_thread(client, thread_id, admin_auth)

        response = client.post(
            f"/api/v1/evaluations/threads/{thread_id}/human-review",
            json={
                "reviewer_name": "r",
                "verdict": "agree",
                "tier_assessment_notes": "n",
                "overridden_recommendation": "stretch",
            },
            headers=admin_auth,
        )

        assert response.status_code == 422

    def test_rejects_override_with_no_overridden_recommendation(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        thread_id: str,
    ) -> None:
        _post_message(client, thread_id, admin_auth, "opening")
        _post_message(client, thread_id, analyst_auth, "reply")
        _complete_thread(client, thread_id, admin_auth)

        response = client.post(
            f"/api/v1/evaluations/threads/{thread_id}/human-review",
            json={"reviewer_name": "r", "verdict": "override", "tier_assessment_notes": "n"},
            headers=admin_auth,
        )

        assert response.status_code == 422

    def test_returns_409_when_a_review_already_exists(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        thread_id: str,
    ) -> None:
        _post_message(client, thread_id, admin_auth, "opening")
        _post_message(client, thread_id, analyst_auth, "reply")
        _complete_thread(client, thread_id, admin_auth)
        payload = {"reviewer_name": "r", "verdict": "agree", "tier_assessment_notes": "n"}
        client.post(
            f"/api/v1/evaluations/threads/{thread_id}/human-review",
            json=payload,
            headers=admin_auth,
        )

        response = client.post(
            f"/api/v1/evaluations/threads/{thread_id}/human-review",
            json=payload,
            headers=admin_auth,
        )

        assert response.status_code == 409

    def test_get_requires_auth(self, client: TestClient, thread_id: str) -> None:
        response = client.get(f"/api/v1/evaluations/threads/{thread_id}/human-review")
        assert response.status_code == 401

    def test_get_forbidden_for_analyst(
        self, client: TestClient, analyst_auth: dict[str, str], thread_id: str
    ) -> None:
        response = client.get(
            f"/api/v1/evaluations/threads/{thread_id}/human-review", headers=analyst_auth
        )
        assert response.status_code == 403

    def test_get_returns_404_when_no_review_exists(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        thread_id: str,
    ) -> None:
        _post_message(client, thread_id, admin_auth, "opening")
        _post_message(client, thread_id, analyst_auth, "reply")
        _complete_thread(client, thread_id, admin_auth)

        response = client.get(
            f"/api/v1/evaluations/threads/{thread_id}/human-review", headers=admin_auth
        )

        assert response.status_code == 404

    def test_get_returns_the_recorded_review(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        thread_id: str,
    ) -> None:
        _post_message(client, thread_id, admin_auth, "opening")
        _post_message(client, thread_id, analyst_auth, "reply")
        _complete_thread(client, thread_id, admin_auth)
        client.post(
            f"/api/v1/evaluations/threads/{thread_id}/human-review",
            json={"reviewer_name": "Prof. Rivera", "verdict": "agree", "tier_assessment_notes": "n"},
            headers=admin_auth,
        )

        response = client.get(
            f"/api/v1/evaluations/threads/{thread_id}/human-review", headers=admin_auth
        )

        assert response.status_code == 200
        assert response.json()["reviewer_name"] == "Prof. Rivera"
