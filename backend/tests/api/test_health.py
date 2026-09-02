"""Unit 6 (MEADOWOPS-API-001): FastAPI app skeleton. /health is the one
deliberately unauthenticated *application* endpoint — deployment platforms
(PRD 8.2) poll it without credentials. (FastAPI's own /docs, /redoc, and
/openapi.json are also unauthenticated by default; security review of this
unit flagged that surface — disabled in app/main.py rather than accepted,
see its comment.)
"""

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_ignores_a_bogus_authorization_header() -> None:
    """Proves /health is genuinely unauthenticated, not just untested with
    no header present."""
    client = TestClient(create_app())
    response = client.get("/health", headers={"Authorization": "Bearer garbage"})
    assert response.status_code == 200


def test_docs_redoc_and_openapi_are_disabled() -> None:
    """Security review of this unit: FastAPI's auto-generated /docs,
    /redoc, and /openapi.json are unauthenticated by default and were
    flagged as an unnecessary information-disclosure surface for a
    two-person internal tool (PRD 5.1) — explicitly disabled rather than
    accepted, before more routes mount in later units.

    Asserts the app's own config, not just route 404s: FastAPI returns 404
    for any unmatched path, so a 404 alone can't distinguish "genuinely
    disabled" from "some other typo'd or moved URL." Checking
    docs_url/redoc_url/openapi_url is None is the actual claim under test.
    """
    app = create_app()
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None

    client = TestClient(app)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
