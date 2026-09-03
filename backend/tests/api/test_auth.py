"""Unit 17a (MEADOWOPS-DOM-010): role-based login (PRD 5.1/8.4 amendment,
S1-FR-16, DD-22) — replaces Unit 6's single shared Builder bearer token.
`POST /api/v1/auth/login` (email+password) issues a signed session token
declaring the caller's role; `/api/v1/me` and every other protected route
now go through `require_authenticated`/`require_admin`
(app/core/auth.py) instead of `require_builder`.

Settings are constructed per-test (via `create_app(settings=...)`), not a
module-level singleton — same reasoning as Unit 6's original test_auth.py.
"""

import os
import uuid
from collections.abc import Generator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.password import hash_password
from app.core.security import create_session_token
from app.db.auth import User
from app.db.enums import UserRole
from app.main import create_app

_SECRET = "test-session-secret-value-at-least-32-bytes-long"
_ADMIN_EMAIL = "zztest-login-admin@meadowops.local"
_ADMIN_PASSWORD = "correct horse battery staple"
_ANALYST_EMAIL = "zztest-login-analyst@meadowops.local"
_ANALYST_PASSWORD = "another correct password"
_SERVICE_TOKEN = "test-internal-service-token-value-at-least-32-bytes-long"


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "session_secret_key": _SECRET,
        "login_rate_limit_max_attempts": 3,
        "login_rate_limit_window_seconds": 900,
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
def seeded_users(db_session: Session) -> Generator[None, None, None]:
    db_session.add(
        User(
            email=_ADMIN_EMAIL,
            password_hash=hash_password(_ADMIN_PASSWORD),
            role=UserRole.ADMIN,
            is_active=True,
        )
    )
    db_session.add(
        User(
            email=_ANALYST_EMAIL,
            password_hash=hash_password(_ANALYST_PASSWORD),
            role=UserRole.ANALYST,
            is_active=True,
        )
    )
    db_session.commit()
    yield
    db_session.execute(delete(User).where(User.email.in_([_ADMIN_EMAIL, _ANALYST_EMAIL])))
    db_session.commit()


def _token(role: str, user_id: str = "test-user") -> str:
    return create_session_token(
        user_id=user_id, role=role, secret=_SECRET, expires_in=timedelta(hours=8)
    )


class TestLogin:
    def test_correct_admin_credentials_return_a_token_and_role(
        self, client: TestClient, seeded_users: None
    ) -> None:
        response = client.post(
            "/api/v1/auth/login", json={"email": _ADMIN_EMAIL, "password": _ADMIN_PASSWORD}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["role"] == "admin"
        assert isinstance(body["access_token"], str) and body["access_token"]

    def test_correct_analyst_credentials_return_the_analyst_role(
        self, client: TestClient, seeded_users: None
    ) -> None:
        response = client.post(
            "/api/v1/auth/login", json={"email": _ANALYST_EMAIL, "password": _ANALYST_PASSWORD}
        )
        assert response.status_code == 200
        assert response.json()["role"] == "analyst"

    def test_login_is_case_insensitive_on_email(
        self, client: TestClient, seeded_users: None
    ) -> None:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": _ADMIN_EMAIL.upper(), "password": _ADMIN_PASSWORD},
        )
        assert response.status_code == 200

    def test_unknown_email_returns_a_generic_401(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@meadowops.local", "password": "whatever"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid credentials"

    def test_wrong_password_returns_the_same_generic_401(
        self, client: TestClient, seeded_users: None
    ) -> None:
        response = client.post(
            "/api/v1/auth/login", json={"email": _ADMIN_EMAIL, "password": "wrong-password"}
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid credentials"

    def test_inactive_user_returns_the_same_generic_401(
        self, client: TestClient, db_session: Session
    ) -> None:
        email = "zztest-login-inactive@meadowops.local"
        db_session.add(
            User(
                email=email,
                password_hash=hash_password("some-password"),
                role=UserRole.ADMIN,
                is_active=False,
            )
        )
        db_session.commit()
        try:
            response = client.post(
                "/api/v1/auth/login", json={"email": email, "password": "some-password"}
            )
            assert response.status_code == 401
            assert response.json()["detail"] == "Invalid credentials"
        finally:
            db_session.execute(delete(User).where(User.email == email))
            db_session.commit()

    def test_the_issued_token_authenticates_against_me(
        self, client: TestClient, seeded_users: None
    ) -> None:
        login_response = client.post(
            "/api/v1/auth/login", json={"email": _ADMIN_EMAIL, "password": _ADMIN_PASSWORD}
        )
        token = login_response.json()["access_token"]
        me_response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
        assert me_response.status_code == 200
        assert me_response.json()["role"] == "admin"

    def test_rate_limits_repeated_failed_attempts_for_the_same_email(
        self, client: TestClient, seeded_users: None
    ) -> None:
        for _ in range(3):
            client.post(
                "/api/v1/auth/login", json={"email": _ADMIN_EMAIL, "password": "wrong"}
            )
        response = client.post(
            "/api/v1/auth/login", json={"email": _ADMIN_EMAIL, "password": _ADMIN_PASSWORD}
        )
        assert response.status_code == 429

    def test_rate_limit_is_scoped_per_email_not_global(
        self, client: TestClient, seeded_users: None
    ) -> None:
        for _ in range(3):
            client.post(
                "/api/v1/auth/login", json={"email": _ADMIN_EMAIL, "password": "wrong"}
            )
        response = client.post(
            "/api/v1/auth/login", json={"email": _ANALYST_EMAIL, "password": _ANALYST_PASSWORD}
        )
        assert response.status_code == 200


class TestMe:
    def test_rejects_a_missing_authorization_header(self, client: TestClient) -> None:
        response = client.get("/api/v1/me")
        assert response.status_code == 401

    def test_rejects_a_malformed_authorization_header(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/me", headers={"Authorization": f"NotBearer {_token('admin')}"}
        )
        assert response.status_code == 401

    def test_rejects_a_token_signed_with_the_wrong_secret(self, client: TestClient) -> None:
        forged = create_session_token(
            user_id="attacker", role="admin", secret="a-different-secret-value-32-bytes!!",
            expires_in=timedelta(hours=8),
        )
        response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {forged}"})
        assert response.status_code == 401

    def test_rejects_an_expired_token(self, client: TestClient) -> None:
        expired = create_session_token(
            user_id="test-user", role="admin", secret=_SECRET, expires_in=timedelta(seconds=-1)
        )
        response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {expired}"})
        assert response.status_code == 401

    def test_accepts_a_valid_admin_token(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/me", headers={"Authorization": f"Bearer {_token('admin')}"}
        )
        assert response.status_code == 200
        assert response.json()["role"] == "admin"

    def test_accepts_a_valid_analyst_token(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/me", headers={"Authorization": f"Bearer {_token('analyst')}"}
        )
        assert response.status_code == 200
        assert response.json()["role"] == "analyst"

    def test_never_echoes_the_token_back_in_the_response(self, client: TestClient) -> None:
        token = _token("admin")
        response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
        assert token not in response.text


class TestSettingsValidation:
    def test_requires_session_secret_key_to_be_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MEADOWOPS_SESSION_SECRET_KEY", raising=False)
        with pytest.raises(Exception):
            Settings(_env_file=None)

    def test_rejects_a_session_secret_key_shorter_than_32_bytes(self) -> None:
        with pytest.raises(Exception):
            Settings(_env_file=None, session_secret_key="too-short")

    def test_requires_internal_service_token_to_be_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MEADOWOPS_INTERNAL_SERVICE_TOKEN", raising=False)
        with pytest.raises(Exception):
            Settings(_env_file=None, session_secret_key=_SECRET)

    def test_rejects_an_internal_service_token_shorter_than_32_bytes(self) -> None:
        with pytest.raises(Exception):
            Settings(
                _env_file=None,
                session_secret_key=_SECRET,
                internal_service_token="too-short",
            )


class TestInternalServiceCredential:
    """Unit 20 (MEADOWOPS-API-004, DD-2): Subsystem 2's internal
    httpx.AsyncClient authenticates with Settings.internal_service_token
    instead of a real user's session JWT. Pre-implementation security
    review of this unit required two structural guarantees, both verified
    directly here: (1) it is granted a real, working identity on ordinary
    require_authenticated read routes; (2) it is rejected everywhere that
    isn't a pure read - require_admin routes via role!="admin" (no new
    code), and Query Playground routes via the new reject_service_role
    dependency specifically added because a route body's own incidental
    UUID-parse ordering was not a real boundary."""

    def test_accepts_the_internal_service_token_at_me(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/me", headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"}
        )
        assert response.status_code == 200
        assert response.json() == {"user_id": "subsystem2-internal", "role": "service"}

    def test_rejects_the_service_token_at_an_admin_gated_route(
        self, client: TestClient
    ) -> None:
        response = client.get(
            "/api/v1/admin/scenarios", headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"}
        )
        assert response.status_code == 403

    def test_rejects_the_service_token_at_query_playground_execute(
        self, client: TestClient
    ) -> None:
        response = client.post(
            "/api/v1/query/execute",
            headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"},
            json={"sql": "select 1", "confirmed": False},
        )
        assert response.status_code == 403

    def test_rejects_the_service_token_at_query_playground_refresh_sandbox(
        self, client: TestClient
    ) -> None:
        response = client.post(
            "/api/v1/query/refresh-sandbox",
            headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"},
        )
        assert response.status_code == 403

    def test_rejects_the_service_token_at_query_playground_history(
        self, client: TestClient
    ) -> None:
        response = client.get(
            "/api/v1/query/history", headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"}
        )
        assert response.status_code == 403

    def test_rejects_the_service_token_at_query_playground_cancel_confirmation(
        self, client: TestClient
    ) -> None:
        response = client.post(
            "/api/v1/query/cancel-confirmation",
            headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"},
            json={"sql": "select 1", "confirmed": False},
        )
        assert response.status_code == 403

    def test_a_garbage_bearer_token_still_401s_not_treated_as_the_service_credential(
        self, client: TestClient
    ) -> None:
        response = client.get(
            "/api/v1/me", headers={"Authorization": "Bearer not-the-real-token"}
        )
        assert response.status_code == 401

    def test_a_non_ascii_bearer_token_401s_and_does_not_500(self, client: TestClient) -> None:
        """Security review of this unit: nothing pinned that both sides of
        `hmac.compare_digest` in app.core.auth stay `.encode("utf-8")`
        bytes, not `str` - Unit 6's own security review already found the
        `str` overload raises `TypeError` (500, not 401) on non-ASCII
        input. Passed as raw bytes deliberately - httpx's own header
        encoder rejects a non-ASCII `str` header client-side before the
        request is even sent, which would only prove the test client is
        strict, not that the server handles it (same reasoning Unit 6's
        original regression test used)."""
        response = client.get(
            "/api/v1/me", headers={"Authorization": b"Bearer not-\xe9-the-token"}
        )
        assert response.status_code == 401

    def test_a_real_admin_token_still_reaches_admin_routes_unaffected(
        self, client: TestClient, seeded_users: None
    ) -> None:
        login_response = client.post(
            "/api/v1/auth/login", json={"email": _ADMIN_EMAIL, "password": _ADMIN_PASSWORD}
        )
        token = login_response.json()["access_token"]
        response = client.get(
            "/api/v1/admin/scenarios", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
