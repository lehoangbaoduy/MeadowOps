"""Unit 28 (MEADOWOPS-API-005, PRD 6.12/S1-FR-14): admin cross-user view of
the Query Playground's query_log — require_admin, unlike Unit 19's own
self-scoped GET /api/v1/query/history (reject_service_role, caller's own
rows only). Reads live.query_log (Unit 19, MEADOWOPS-DOMAIN-010), no new
table. Fixture pattern follows test_query_playground_api.py.
"""

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.auth import User
from app.db.enums import UserRole
from app.db.query_log import QueryLog
from app.main import create_app
from tests.support.auth import TEST_SESSION_SECRET, make_token

_ANALYST_EMAIL = "zztest-admin-query-log-analyst@meadowops.local"
_ADMIN_EMAIL = "zztest-admin-query-log-admin@meadowops.local"


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
    def test_requires_authentication(self, client: TestClient) -> None:
        response = client.get("/api/v1/admin/query-log")
        assert response.status_code == 401

    def test_analyst_is_rejected(self, client: TestClient, analyst_auth: dict[str, str]) -> None:
        response = client.get("/api/v1/admin/query-log", headers=analyst_auth)
        assert response.status_code == 403


class TestAdminQueryLog:
    def test_returns_rows_from_multiple_users_not_just_the_caller(
        self,
        client: TestClient,
        analyst_auth: dict[str, str],
        admin_auth: dict[str, str],
        analyst_user_id: str,
        admin_user_id: str,
    ) -> None:
        analyst_sql = "select 'zztest-admin-query-log-marker-analyst' as marker"
        admin_sql = "select 'zztest-admin-query-log-marker-admin' as marker"
        client.post("/api/v1/query/execute", json={"sql": analyst_sql}, headers=analyst_auth)
        client.post("/api/v1/query/execute", json={"sql": admin_sql}, headers=admin_auth)

        response = client.get("/api/v1/admin/query-log?limit=500", headers=admin_auth)
        assert response.status_code == 200
        body = response.json()

        query_texts = {entry["query_text"] for entry in body}
        assert analyst_sql in query_texts
        assert admin_sql in query_texts

        by_text = {entry["query_text"]: entry for entry in body}
        assert by_text[analyst_sql]["user_email"] == _ANALYST_EMAIL
        assert by_text[admin_sql]["user_email"] == _ADMIN_EMAIL

    def test_own_self_scoped_history_route_does_not_see_the_other_users_row(
        self,
        client: TestClient,
        analyst_auth: dict[str, str],
        admin_auth: dict[str, str],
        analyst_user_id: str,
        admin_user_id: str,
    ) -> None:
        admin_only_sql = "select 'zztest-admin-query-log-self-scope-marker' as marker"
        client.post("/api/v1/query/execute", json={"sql": admin_only_sql}, headers=admin_auth)

        response = client.get("/api/v1/query/history", headers=analyst_auth)
        assert response.status_code == 200
        assert all(entry["query_text"] != admin_only_sql for entry in response.json())

    def test_full_query_text_is_present_uncut_for_a_long_statement(
        self, client: TestClient, admin_auth: dict[str, str], admin_user_id: str
    ) -> None:
        long_marker = "x" * 300
        long_sql = f"select '{long_marker}' as marker"
        client.post("/api/v1/query/execute", json={"sql": long_sql}, headers=admin_auth)

        response = client.get("/api/v1/admin/query-log?limit=500", headers=admin_auth)
        assert response.status_code == 200
        query_texts = {entry["query_text"] for entry in response.json()}
        assert long_sql in query_texts

    def test_pagination_limit_is_honoured(
        self, client: TestClient, admin_auth: dict[str, str], admin_user_id: str
    ) -> None:
        for i in range(3):
            client.post(
                "/api/v1/query/execute",
                json={"sql": f"select {i} as zztest_admin_query_log_pagination"},
                headers=admin_auth,
            )

        response = client.get("/api/v1/admin/query-log?limit=1", headers=admin_auth)
        assert response.status_code == 200
        assert len(response.json()) == 1
