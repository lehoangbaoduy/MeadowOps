"""Unit 24 (MEADOWOPS-DOM-018, PRD 4.4): Decision & Event Ledger API.
Write routes are require_admin (PRD 376: admin-panel controls are
Builder-only). Read routes are require_authenticated, not require_admin -
unlike U23's chat routes, nothing here is ground-truth-secret from the
Analyst, and Subsystem 2's internal-service credential must also reach the
callback-candidates lookup (see tests/integration/test_subsystem2_boundary.py
for the real ASGI round trip through that specific route).
"""

import os
import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.auth import User
from app.db.enums import UserRole
from app.db.ledger import DecisionEvent
from app.main import create_app
from app.services.baseline_data import seed_master_data
from tests.support.auth import TEST_SESSION_SECRET, make_token

_ADMIN_EMAIL = "zztest-ledger-api-admin@meadowops.local"
_ANALYST_AUTH = {"Authorization": f"Bearer {make_token('analyst')}"}


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
    user = User(email=_ADMIN_EMAIL, password_hash="not-a-real-hash", role=UserRole.ADMIN, is_active=True)
    db_session.add(user)
    db_session.commit()
    yield str(user.id)
    db_session.execute(delete(DecisionEvent))
    db_session.execute(delete(User).where(User.email == _ADMIN_EMAIL))
    db_session.commit()


@pytest.fixture
def admin_auth(admin_user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token('admin', user_id=admin_user_id)}"}


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(create_app(settings=Settings(session_secret_key=TEST_SESSION_SECRET))) as c:
        yield c


def _propose_payload(**overrides) -> dict:
    payload = {
        "entity_type": "supplier",
        "entity_id": "SUP-001",
        "title": "Move 40% of SKU-100 volume to Supplier S-002",
        "summary": "Supplier S-001 has repeated late shipments.",
    }
    payload.update(overrides)
    return payload


def _propose(client: TestClient, admin_auth: dict, **overrides) -> str:
    response = client.post(
        "/api/v1/ledger/decisions", json=_propose_payload(**overrides), headers=admin_auth
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


class TestProposeRoute:
    def test_requires_auth(self, client: TestClient) -> None:
        assert client.post("/api/v1/ledger/decisions", json=_propose_payload()).status_code == 401

    def test_forbidden_for_analyst(self, client: TestClient, admin_user_id: str) -> None:
        response = client.post(
            "/api/v1/ledger/decisions", json=_propose_payload(), headers=_ANALYST_AUTH
        )
        assert response.status_code == 403

    def test_happy_path_creates_a_proposed_decision(
        self, client: TestClient, admin_auth: dict
    ) -> None:
        response = client.post(
            "/api/v1/ledger/decisions", json=_propose_payload(), headers=admin_auth
        )
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "proposed"
        assert uuid.UUID(body["id"])

    def test_an_unknown_supersedes_id_returns_409(self, client: TestClient, admin_auth: dict) -> None:
        response = client.post(
            "/api/v1/ledger/decisions",
            json=_propose_payload(supersedes_id=str(uuid.uuid4())),
            headers=admin_auth,
        )
        assert response.status_code == 409

    def test_operational_event_record_type_is_rejected(
        self, client: TestClient, admin_auth: dict
    ) -> None:
        # Code review, HIGH: the route structurally can't create an
        # operational_event row (schemas/ledger.py restricts record_type to
        # Literal["decision"]) - FastAPI 422s before the route body runs.
        response = client.post(
            "/api/v1/ledger/decisions",
            json=_propose_payload(record_type="operational_event"),
            headers=admin_auth,
        )
        assert response.status_code == 422


class TestResubmitRoute:
    def test_moves_clarification_requested_back_to_proposed(
        self, client: TestClient, admin_auth: dict
    ) -> None:
        decision_id = _propose(client, admin_auth)
        client.post(
            f"/api/v1/ledger/decisions/{decision_id}/request-clarification", json={}, headers=admin_auth
        )
        response = client.post(
            f"/api/v1/ledger/decisions/{decision_id}/resubmit", json={}, headers=admin_auth
        )
        assert response.status_code == 200
        assert response.json()["status"] == "proposed"

    def test_is_forbidden_for_analyst(self, client: TestClient, admin_auth: dict) -> None:
        decision_id = _propose(client, admin_auth)
        client.post(
            f"/api/v1/ledger/decisions/{decision_id}/request-clarification", json={}, headers=admin_auth
        )
        response = client.post(
            f"/api/v1/ledger/decisions/{decision_id}/resubmit", json={}, headers=_ANALYST_AUTH
        )
        assert response.status_code == 403

    def test_invalid_transition_returns_409(self, client: TestClient, admin_auth: dict) -> None:
        decision_id = _propose(client, admin_auth)
        response = client.post(
            f"/api/v1/ledger/decisions/{decision_id}/resubmit", json={}, headers=admin_auth
        )
        assert response.status_code == 409


class TestTransitionRoutes:
    def test_accept_moves_to_accepted(self, client: TestClient, admin_auth: dict) -> None:
        decision_id = _propose(client, admin_auth)
        response = client.post(f"/api/v1/ledger/decisions/{decision_id}/accept", json={}, headers=admin_auth)
        assert response.status_code == 200
        assert response.json()["status"] == "accepted"

    def test_accept_is_forbidden_for_analyst(self, client: TestClient, admin_auth: dict) -> None:
        decision_id = _propose(client, admin_auth)
        response = client.post(
            f"/api/v1/ledger/decisions/{decision_id}/accept", json={}, headers=_ANALYST_AUTH
        )
        assert response.status_code == 403

    def test_reject_moves_to_rejected(self, client: TestClient, admin_auth: dict) -> None:
        decision_id = _propose(client, admin_auth)
        response = client.post(f"/api/v1/ledger/decisions/{decision_id}/reject", json={}, headers=admin_auth)
        assert response.status_code == 200
        assert response.json()["status"] == "rejected"

    def test_invalid_transition_returns_409(self, client: TestClient, admin_auth: dict) -> None:
        decision_id = _propose(client, admin_auth)
        client.post(f"/api/v1/ledger/decisions/{decision_id}/reject", json={}, headers=admin_auth)
        response = client.post(f"/api/v1/ledger/decisions/{decision_id}/accept", json={}, headers=admin_auth)
        assert response.status_code == 409

    def test_unknown_decision_returns_404(self, client: TestClient, admin_auth: dict) -> None:
        response = client.post(
            f"/api/v1/ledger/decisions/{uuid.uuid4()}/accept", json={}, headers=admin_auth
        )
        assert response.status_code == 404

    def test_full_lifecycle_through_to_outcome(self, client: TestClient, admin_auth: dict) -> None:
        decision_id = _propose(client, admin_auth)
        client.post(f"/api/v1/ledger/decisions/{decision_id}/accept", json={}, headers=admin_auth)
        implemented = client.post(
            f"/api/v1/ledger/decisions/{decision_id}/implement", json={}, headers=admin_auth
        )
        assert implemented.json()["status"] == "implemented"
        outcome = client.post(
            f"/api/v1/ledger/decisions/{decision_id}/outcome",
            json={"outcome": "succeeded", "notes": "Improved on-time rate."},
            headers=admin_auth,
        )
        assert outcome.status_code == 200
        assert outcome.json()["status"] == "outcome_observed"
        assert outcome.json()["outcome"] == "succeeded"


class TestReadRoutes:
    def test_list_requires_auth(self, client: TestClient) -> None:
        assert client.get("/api/v1/ledger/decisions").status_code == 401

    def test_list_is_readable_by_analyst(self, client: TestClient, admin_auth: dict) -> None:
        _propose(client, admin_auth)
        response = client.get("/api/v1/ledger/decisions", headers=_ANALYST_AUTH)
        assert response.status_code == 200
        assert len(response.json()) >= 1

    def test_get_by_id_returns_404_for_unknown_id(self, client: TestClient, admin_auth: dict) -> None:
        response = client.get(f"/api/v1/ledger/decisions/{uuid.uuid4()}", headers=admin_auth)
        assert response.status_code == 404

    def test_callback_candidates_route_is_readable_by_analyst(
        self, client: TestClient, admin_auth: dict
    ) -> None:
        decision_id = _propose(client, admin_auth, entity_id="SUP-777")
        client.post(f"/api/v1/ledger/decisions/{decision_id}/accept", json={}, headers=admin_auth)
        client.post(f"/api/v1/ledger/decisions/{decision_id}/implement", json={}, headers=admin_auth)
        response = client.get(
            "/api/v1/ledger/entities/supplier/SUP-777/callback-candidates", headers=_ANALYST_AUTH
        )
        assert response.status_code == 200
        assert [d["id"] for d in response.json()] == [decision_id]
