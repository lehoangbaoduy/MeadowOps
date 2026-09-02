"""Unit 6 (MEADOWOPS-API-001): the Builder auth stub (PRD 8.4: "restrict
admin operations to the Builder"; PRD 5.1 explicitly puts auth/multi-tenant
complexity beyond two users out of scope — this is a deliberately minimal
shared-bearer-token check, not a full identity system). `/api/v1/me` is the
one endpoint exercising it end-to-end in this unit; later units (admin CRUD,
Query Playground) reuse the same `require_builder` dependency.

Settings are constructed per-test (via `create_app(settings=...)`), not
imported as a module-level singleton — env-var monkeypatching wouldn't
reliably reach a cached global across tests otherwise.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

_TOKEN = "test-builder-token-value"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(settings=Settings(builder_token=_TOKEN)))


def test_me_rejects_a_missing_authorization_header(client: TestClient) -> None:
    response = client.get("/api/v1/me")
    assert response.status_code == 401


def test_me_rejects_a_malformed_authorization_header(client: TestClient) -> None:
    response = client.get("/api/v1/me", headers={"Authorization": f"NotBearer {_TOKEN}"})
    assert response.status_code == 401


def test_me_rejects_the_wrong_token(client: TestClient) -> None:
    response = client.get("/api/v1/me", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401


def test_me_rejects_a_non_ascii_token_without_crashing(client: TestClient) -> None:
    """Security review of this unit: hmac.compare_digest's str overload
    raises TypeError on non-ASCII input instead of returning False, which
    turned an unauthenticated 401 into a 500 (Starlette decodes header
    values as latin-1, so any byte >= 0x80 survives as non-ASCII str).
    Fixed by comparing bytes instead — this is the regression test. The
    header value is passed as raw latin-1-encoded bytes, not a plain str:
    httpx's client-side header encoder rejects a non-ASCII str value
    itself (UnicodeEncodeError) before a request is even sent, which would
    only prove the test client is strict, not that the server handles it."""
    response = client.get(
        "/api/v1/me", headers={"Authorization": "Bearer café".encode("latin-1")}
    )
    assert response.status_code == 401


def test_me_accepts_the_correct_builder_token(client: TestClient) -> None:
    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {_TOKEN}"})
    assert response.status_code == 200
    assert response.json() == {"role": "builder"}


def test_me_never_echoes_the_token_back_in_the_response(client: TestClient) -> None:
    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {_TOKEN}"})
    assert _TOKEN not in response.text


def test_settings_requires_builder_token_to_be_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Security rule: required secrets validated at startup, not discovered
    as a 401 surprise at request time. No default and no env var present ->
    pydantic-settings raises at construction, not later. Explicitly
    clears the env var (conftest.py's load_dotenv already populated
    os.environ from the real .env for the whole test process — _env_file=
    None only disables re-reading the dotenv file, not ambient os.environ)."""
    monkeypatch.delenv("MEADOWOPS_BUILDER_TOKEN", raising=False)
    with pytest.raises(Exception):
        Settings(_env_file=None)


def test_settings_rejects_an_empty_builder_token() -> None:
    """An explicitly-set empty string is also not a valid token — an empty
    Authorization: Bearer  header would otherwise satisfy it."""
    with pytest.raises(Exception):
        Settings(_env_file=None, builder_token="")
