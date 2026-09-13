"""Unit 26 (MEADOWOPS-DOM-020, PRD 6.10): portfolio routes -
`record_reflection_route` is reject_service_role (Analyst can author her
own reflection); `get_portfolio_export_route` is admin-only (ER-5: the
compiled export embeds the full draft evaluation, including
difficulty_recommendation).
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
_ADMIN_EMAIL = "zztest-portfolio-api-admin@meadowops.local"
_ANALYST_EMAIL = "zztest-portfolio-api-analyst@meadowops.local"
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

_REFLECTION_PAYLOAD = {
    "reflection_what_happened": "A stockout on SKU-COR-001 at WH-EAST.",
    "reflection_initial_thought": "I assumed the supplier was late.",
    "reflection_evidence_that_mattered": "The reorder point history.",
    "reflection_what_missed": "The lead-time trend at first.",
    "reflection_what_changed_after_pushback": "I checked the reorder point config.",
    "reflection_what_differently": "Check configuration before blaming the supplier.",
    "reflection_skill_improved": "Root-cause analysis.",
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
        title="zztest portfolio api scenario",
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
    # test_evaluation_api.py's own scenario_id fixture - duplicated rather
    # than imported, this project's established per-test-file convention.
    # portfolio_artifact FK-references chat_thread (deleted first, same as
    # chat_message/human_review below); human_review FK-references
    # evaluation (deleted first, same reasoning as test_evaluation_api.py).
    with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "delete from chat.chat_thread_read_state where thread_id in "
            "(select id from chat.chat_thread where scenario_id = %s)",
            (scenario.id,),
        )
        cur.execute(
            "alter table engine.portfolio_artifact disable trigger portfolio_artifact_no_delete"
        )
        try:
            cur.execute(
                "delete from engine.portfolio_artifact where thread_id in "
                "(select id from chat.chat_thread where scenario_id = %s)",
                (scenario.id,),
            )
        finally:
            cur.execute(
                "alter table engine.portfolio_artifact enable trigger portfolio_artifact_no_delete"
            )
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


@pytest.fixture
def completed_thread_id(
    client: TestClient, admin_auth: dict[str, str], analyst_auth: dict[str, str], thread_id: str
) -> str:
    _post_message(client, thread_id, admin_auth, "East's service is getting worse.")
    _post_message(client, thread_id, analyst_auth, "Reorder point looks misconfigured.")
    _complete_thread(client, thread_id, admin_auth)
    return thread_id


class TestRecordReflectionRoute:
    def test_requires_auth(self, client: TestClient, completed_thread_id: str) -> None:
        response = client.post(
            f"/api/v1/portfolio/threads/{completed_thread_id}/reflection",
            json=_REFLECTION_PAYLOAD,
        )
        assert response.status_code == 401

    def test_service_credential_cannot_author_a_reflection(
        self, client: TestClient, completed_thread_id: str
    ) -> None:
        response = client.post(
            f"/api/v1/portfolio/threads/{completed_thread_id}/reflection",
            json=_REFLECTION_PAYLOAD,
            headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"},
        )
        assert response.status_code == 403

    def test_analyst_can_author_her_own_reflection(
        self,
        client: TestClient,
        analyst_auth: dict[str, str],
        completed_thread_id: str,
        analyst_user_id: str,
        owner_dsn: str,
    ) -> None:
        response = client.post(
            f"/api/v1/portfolio/threads/{completed_thread_id}/reflection",
            json=_REFLECTION_PAYLOAD,
            headers=analyst_auth,
        )

        assert response.status_code == 201
        body = response.json()
        assert body["reflection_skill_improved"] == "Root-cause analysis."
        # Security check: the Analyst's own write response must never leak
        # anything ER-5 protects.
        assert "evaluation" not in body
        assert "difficulty_recommendation" not in body
        # Security review of this unit: the route must populate
        # submitted_by_user_id from the authenticated identity - checked
        # against the DB row directly since PortfolioReflectionRead
        # deliberately doesn't expose this column.
        with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "select submitted_by_user_id from engine.portfolio_artifact where id = %s",
                (body["id"],),
            )
            (submitted_by_user_id,) = cur.fetchone()
        assert str(submitted_by_user_id) == analyst_user_id

    def test_admin_can_author_a_reflection(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        completed_thread_id: str,
        admin_user_id: str,
        owner_dsn: str,
    ) -> None:
        response = client.post(
            f"/api/v1/portfolio/threads/{completed_thread_id}/reflection",
            json=_REFLECTION_PAYLOAD,
            headers=admin_auth,
        )
        assert response.status_code == 201
        with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "select submitted_by_user_id from engine.portfolio_artifact where id = %s",
                (response.json()["id"],),
            )
            (submitted_by_user_id,) = cur.fetchone()
        assert str(submitted_by_user_id) == admin_user_id

    def test_returns_409_when_the_thread_is_not_completed(
        self, client: TestClient, analyst_auth: dict[str, str], thread_id: str
    ) -> None:
        response = client.post(
            f"/api/v1/portfolio/threads/{thread_id}/reflection",
            json=_REFLECTION_PAYLOAD,
            headers=analyst_auth,
        )
        assert response.status_code == 409

    def test_returns_404_for_an_unknown_thread(
        self, client: TestClient, analyst_auth: dict[str, str]
    ) -> None:
        response = client.post(
            f"/api/v1/portfolio/threads/{uuid.uuid4()}/reflection",
            json=_REFLECTION_PAYLOAD,
            headers=analyst_auth,
        )
        assert response.status_code == 404

    def test_returns_409_when_a_reflection_already_exists(
        self, client: TestClient, analyst_auth: dict[str, str], completed_thread_id: str
    ) -> None:
        client.post(
            f"/api/v1/portfolio/threads/{completed_thread_id}/reflection",
            json=_REFLECTION_PAYLOAD,
            headers=analyst_auth,
        )

        response = client.post(
            f"/api/v1/portfolio/threads/{completed_thread_id}/reflection",
            json=_REFLECTION_PAYLOAD,
            headers=analyst_auth,
        )

        assert response.status_code == 409

    def test_rejects_an_empty_answer(
        self, client: TestClient, analyst_auth: dict[str, str], completed_thread_id: str
    ) -> None:
        payload = {**_REFLECTION_PAYLOAD, "reflection_what_happened": ""}
        response = client.post(
            f"/api/v1/portfolio/threads/{completed_thread_id}/reflection",
            json=payload,
            headers=analyst_auth,
        )
        assert response.status_code == 422


class TestGetPortfolioExportRoute:
    def test_requires_auth(self, client: TestClient, completed_thread_id: str) -> None:
        response = client.get(f"/api/v1/portfolio/threads/{completed_thread_id}")
        assert response.status_code == 401

    def test_forbidden_for_analyst(
        self, client: TestClient, analyst_auth: dict[str, str], completed_thread_id: str
    ) -> None:
        response = client.get(
            f"/api/v1/portfolio/threads/{completed_thread_id}", headers=analyst_auth
        )
        assert response.status_code == 403

    def test_returns_404_for_an_unknown_thread(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        response = client.get(f"/api/v1/portfolio/threads/{uuid.uuid4()}", headers=admin_auth)
        assert response.status_code == 404

    def test_returns_409_when_the_thread_is_not_completed(
        self, client: TestClient, admin_auth: dict[str, str], thread_id: str
    ) -> None:
        response = client.get(f"/api/v1/portfolio/threads/{thread_id}", headers=admin_auth)
        assert response.status_code == 409

    def test_compiles_with_no_review_and_no_reflection(
        self, client: TestClient, admin_auth: dict[str, str], completed_thread_id: str
    ) -> None:
        response = client.get(
            f"/api/v1/portfolio/threads/{completed_thread_id}", headers=admin_auth
        )

        assert response.status_code == 200
        body = response.json()
        assert body["trigger"] == "East's service is getting worse."
        assert body["evaluation"]["difficulty_recommendation"] == "standard"
        assert body["human_review"] is None
        assert body["reflection"] is None

    def test_compiles_with_a_review_and_a_reflection(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        analyst_auth: dict[str, str],
        completed_thread_id: str,
    ) -> None:
        client.post(
            f"/api/v1/evaluations/threads/{completed_thread_id}/human-review",
            json={
                "reviewer_name": "Prof. Rivera",
                "verdict": "override",
                "tier_assessment_notes": "Evidence supports a stretch call.",
                "overridden_recommendation": "stretch",
            },
            headers=admin_auth,
        )
        client.post(
            f"/api/v1/portfolio/threads/{completed_thread_id}/reflection",
            json=_REFLECTION_PAYLOAD,
            headers=analyst_auth,
        )

        response = client.get(
            f"/api/v1/portfolio/threads/{completed_thread_id}", headers=admin_auth
        )

        assert response.status_code == 200
        body = response.json()
        assert body["human_review"]["verdict"] == "override"
        assert body["reflection"]["reflection_skill_improved"] == "Root-cause analysis."
