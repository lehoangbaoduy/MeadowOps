"""Unit 19 (MEADOWOPS-DOM-012): Query Playground API — every route is
require_authenticated (both Admin and Analyst, PRD 5.9), unlike Unit 18's
Builder-only scenario controls. QueryLog.user_id has a hard FK to
live.user.id (same gotcha Unit 18 hit), so tokens here are minted against a
real seeded `live.user` row, following test_admin_scenarios.py's own
pattern.
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
from app.db.base import Base
from app.db.enums import UserRole
from app.db.query_log import QueryLog
from app.main import create_app
from app.services.sandbox_refresh import refresh_sandbox
from tests.support.auth import TEST_SESSION_SECRET, make_token

_ANALYST_EMAIL = "zztest-query-playground-analyst@meadowops.local"
_ADMIN_EMAIL = "zztest-query-playground-admin@meadowops.local"


@pytest.fixture(scope="module", autouse=True)
def _refreshed_sandbox() -> None:
    import app.db  # noqa: F401 - registers every table on Base.metadata

    owner_dsn = (
        f"host=localhost port=5434 dbname=meadowops user=meadowops "
        f"password={os.environ['MEADOWOPS_POSTGRES_PASSWORD']}"
    )
    result = refresh_sandbox(owner_dsn, Base.metadata)
    assert result.status.value == "complete"


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def analyst_user_id(db_session: Session) -> Generator[str, None, None]:
    db_session.execute(delete(User).where(User.email == _ANALYST_EMAIL))
    db_session.commit()
    user = User(
        email=_ANALYST_EMAIL, password_hash="not-a-real-hash", role=UserRole.ANALYST, is_active=True
    )
    db_session.add(user)
    db_session.commit()
    yield str(user.id)
    db_session.execute(delete(QueryLog).where(QueryLog.user_id == user.id))
    db_session.execute(delete(User).where(User.email == _ANALYST_EMAIL))
    db_session.commit()


@pytest.fixture
def admin_user_id(db_session: Session) -> Generator[str, None, None]:
    db_session.execute(delete(User).where(User.email == _ADMIN_EMAIL))
    db_session.commit()
    user = User(
        email=_ADMIN_EMAIL, password_hash="not-a-real-hash", role=UserRole.ADMIN, is_active=True
    )
    db_session.add(user)
    db_session.commit()
    yield str(user.id)
    db_session.execute(delete(QueryLog).where(QueryLog.user_id == user.id))
    db_session.execute(delete(User).where(User.email == _ADMIN_EMAIL))
    db_session.commit()


@pytest.fixture
def analyst_auth(analyst_user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token('analyst', user_id=analyst_user_id)}"}


@pytest.fixture
def admin_auth(admin_user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token('admin', user_id=admin_user_id)}"}


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(create_app(settings=Settings(session_secret_key=TEST_SESSION_SECRET))) as c:
        yield c


class TestAuth:
    def test_execute_requires_authentication(self, client: TestClient) -> None:
        response = client.post("/api/v1/query/execute", json={"sql": "select 1"})
        assert response.status_code == 401

    def test_refresh_requires_authentication(self, client: TestClient) -> None:
        response = client.post("/api/v1/query/refresh-sandbox")
        assert response.status_code == 401

    def test_history_requires_authentication(self, client: TestClient) -> None:
        response = client.get("/api/v1/query/history")
        assert response.status_code == 401

    def test_analyst_can_execute_a_read_query(
        self, client: TestClient, analyst_auth: dict[str, str]
    ) -> None:
        response = client.post(
            "/api/v1/query/execute", json={"sql": "select 1 as one"}, headers=analyst_auth
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    def test_admin_can_execute_a_read_query(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        response = client.post(
            "/api/v1/query/execute", json={"sql": "select 1 as one"}, headers=admin_auth
        )
        assert response.status_code == 200

    def test_malformed_token_subject_returns_401_not_500(self, client: TestClient) -> None:
        bad_auth = {"Authorization": f"Bearer {make_token('admin', user_id='not-a-uuid')}"}
        response = client.post(
            "/api/v1/query/execute", json={"sql": "select 1"}, headers=bad_auth
        )
        assert response.status_code == 401


class TestExecute:
    def test_read_query_returns_rows_and_logs_success(
        self, client: TestClient, analyst_auth: dict[str, str], db_session: Session, analyst_user_id: str
    ) -> None:
        response = client.post(
            "/api/v1/query/execute",
            json={"sql": "select id, sku from sandbox.product limit 3"},
            headers=analyst_auth,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["columns"] == ["id", "sku"]

        db_session.expire_all()
        rows = db_session.query(QueryLog).filter(QueryLog.user_id == uuid.UUID(analyst_user_id)).all()
        assert len(rows) == 1
        assert rows[0].result_status.value == "success"
        assert rows[0].statement_type.value == "read"

    def test_write_without_confirmed_returns_confirmation_required_and_does_not_log(
        self, client: TestClient, analyst_auth: dict[str, str], db_session: Session, analyst_user_id: str
    ) -> None:
        response = client.post(
            "/api/v1/query/execute",
            json={"sql": "delete from sandbox.product where 1 = 0"},
            headers=analyst_auth,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "confirmation_required"

        db_session.expire_all()
        rows = db_session.query(QueryLog).filter(QueryLog.user_id == uuid.UUID(analyst_user_id)).all()
        assert rows == []

    def test_write_with_confirmed_true_executes_and_logs_write(
        self, client: TestClient, analyst_auth: dict[str, str], db_session: Session, analyst_user_id: str
    ) -> None:
        response = client.post(
            "/api/v1/query/execute",
            json={"sql": "delete from sandbox.product where 1 = 0", "confirmed": True},
            headers=analyst_auth,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"

        db_session.expire_all()
        rows = db_session.query(QueryLog).filter(QueryLog.user_id == uuid.UUID(analyst_user_id)).all()
        assert len(rows) == 1
        assert rows[0].statement_type.value == "write"

    def test_malformed_sql_returns_clean_error(
        self, client: TestClient, analyst_auth: dict[str, str]
    ) -> None:
        response = client.post(
            "/api/v1/query/execute", json={"sql": "select * frooom nowhere"}, headers=analyst_auth
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "error"
        assert "Traceback" not in body["error_message"]


class TestCancelConfirmation:
    def test_declining_logs_a_cancelled_row(
        self, client: TestClient, analyst_auth: dict[str, str], db_session: Session, analyst_user_id: str
    ) -> None:
        response = client.post(
            "/api/v1/query/cancel-confirmation",
            json={"sql": "drop table sandbox.product"},
            headers=analyst_auth,
        )
        assert response.status_code == 204

        db_session.expire_all()
        rows = db_session.query(QueryLog).filter(QueryLog.user_id == uuid.UUID(analyst_user_id)).all()
        assert len(rows) == 1
        assert rows[0].result_status.value == "cancelled"


class TestHistory:
    def test_history_returns_only_the_caller_own_submissions(
        self,
        client: TestClient,
        analyst_auth: dict[str, str],
        admin_auth: dict[str, str],
    ) -> None:
        client.post("/api/v1/query/execute", json={"sql": "select 1"}, headers=analyst_auth)
        client.post("/api/v1/query/execute", json={"sql": "select 2"}, headers=admin_auth)

        response = client.get("/api/v1/query/history", headers=analyst_auth)
        assert response.status_code == 200
        body = response.json()
        assert len(body) >= 1
        assert all(entry["query_text"] != "select 2" for entry in body)


class TestRefreshSandbox:
    def test_refresh_returns_complete_with_mirrored_tables(
        self, client: TestClient, analyst_auth: dict[str, str]
    ) -> None:
        response = client.post("/api/v1/query/refresh-sandbox", headers=analyst_auth)
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "complete"
        assert body["tables_mirrored"] > 0
