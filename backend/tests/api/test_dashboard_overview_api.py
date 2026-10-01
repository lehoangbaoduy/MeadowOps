"""Unit 41: GET /api/v1/dashboard/overview - the Overview page's one read.
Open to both signed-in humans, closed to the internal service credential
(Subsystem 2 has no use for it), with the window length bounded."""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.architecture.test_subsystem_boundary import _classify_routes
from tests.support.auth import TEST_SESSION_SECRET, make_token

_URL = "/api/v1/dashboard/overview"
_ADMIN = {"Authorization": f"Bearer {make_token('admin')}"}
_ANALYST = {"Authorization": f"Bearer {make_token('analyst')}"}


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(create_app(settings=Settings(session_secret_key=TEST_SESSION_SECRET))) as c:
        yield c


def test_requires_a_signed_in_user(client: TestClient) -> None:
    assert client.get(_URL).status_code == 401


@pytest.mark.parametrize("headers", [_ADMIN, _ANALYST])
def test_both_humans_can_read_it(client: TestClient, headers: dict[str, str]) -> None:
    response = client.get(_URL, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["window_days"] == 30
    assert len(body["daily_activity"]) == 30
    assert len(body["new_exceptions_per_day"]) == 30
    assert body["window_start"] <= body["as_of"]


def test_the_window_length_is_honoured(client: TestClient) -> None:
    body = client.get(f"{_URL}?days=14", headers=_ANALYST).json()

    assert body["window_days"] == 14
    assert len(body["daily_activity"]) == 14


@pytest.mark.parametrize("days", [0, 6, 91, "abc"])
def test_an_out_of_range_window_is_rejected(client: TestClient, days) -> None:
    assert client.get(f"{_URL}?days={days}", headers=_ANALYST).status_code == 422


def test_the_internal_service_credential_is_kept_out() -> None:
    assert _classify_routes()[("GET", "/api/v1/dashboard/overview")] == "service_rejected"
