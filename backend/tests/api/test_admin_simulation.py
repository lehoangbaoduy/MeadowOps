"""Unit 40: POST /api/v1/admin/simulation/repopulate starts the destructive
"Reset & regenerate to today" job, GET .../status reports it. Admin-only, and
the typed confirmation is enforced on the server, not just in the UI. The
real rebuild is replaced by a fake so no test wipes the shared dev database."""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.api import admin_simulation
from app.core.config import Settings
from app.main import create_app
from tests.support.auth import TEST_SESSION_SECRET, make_token

_ADMIN = {"Authorization": f"Bearer {make_token('admin')}"}
_ANALYST = {"Authorization": f"Bearer {make_token('analyst')}"}
_URL = "/api/v1/admin/simulation/repopulate"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    calls: list[dict] = []

    def fake_work(engine, settings, *, today, history_days):
        calls.append({"today": today, "history_days": history_days})
        return lambda progress: f"Rebuilt {history_days} days"

    monkeypatch.setattr(admin_simulation, "build_repopulate_work", fake_work)
    with TestClient(create_app(settings=Settings(session_secret_key=TEST_SESSION_SECRET))) as c:
        c.calls = calls  # type: ignore[attr-defined]
        yield c


def _wait(client: TestClient) -> None:
    client.app.state.repopulate_job.join(timeout=5)


class TestRepopulateRoute:
    def test_requires_a_signed_in_user(self, client: TestClient) -> None:
        assert client.post(_URL, json={"confirm": "REPOPULATE"}).status_code == 401

    def test_an_analyst_is_forbidden(self, client: TestClient) -> None:
        response = client.post(_URL, json={"confirm": "REPOPULATE"}, headers=_ANALYST)
        assert response.status_code == 403
        assert client.calls == []

    def test_a_missing_or_wrong_confirmation_is_rejected_and_does_nothing(
        self, client: TestClient
    ) -> None:
        for body in ({}, {"confirm": "yes"}, {"confirm": "repopulate"}):
            assert client.post(_URL, json=body, headers=_ADMIN).status_code == 422
        assert client.calls == []

    def test_the_history_length_is_bounded(self, client: TestClient) -> None:
        for days in (0, 13, 91):
            response = client.post(
                _URL, json={"confirm": "REPOPULATE", "history_days": days}, headers=_ADMIN
            )
            assert response.status_code == 422
        assert client.calls == []

    def test_a_confirmed_request_starts_the_job_and_reports_success(
        self, client: TestClient
    ) -> None:
        response = client.post(_URL, json={"confirm": "REPOPULATE"}, headers=_ADMIN)
        _wait(client)

        assert response.status_code == 202
        assert response.json()["state"] in {"running", "succeeded"}
        assert len(client.calls) == 1
        assert client.calls[0]["history_days"] == 45
        status = client.get(f"{_URL}/status", headers=_ADMIN).json()
        assert status["state"] == "succeeded"
        assert status["message"] == "Rebuilt 45 days"

    def test_a_second_request_while_one_is_running_is_a_conflict(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import threading

        release = threading.Event()
        monkeypatch.setattr(
            admin_simulation,
            "build_repopulate_work",
            lambda *a, **k: (lambda progress: release.wait(timeout=5) and "done"),
        )
        first = client.post(_URL, json={"confirm": "REPOPULATE"}, headers=_ADMIN)
        second = client.post(_URL, json={"confirm": "REPOPULATE"}, headers=_ADMIN)
        release.set()
        _wait(client)

        assert first.status_code == 202
        assert second.status_code == 409


class TestStatusRoute:
    def test_is_idle_before_any_run(self, client: TestClient) -> None:
        response = client.get(f"{_URL}/status", headers=_ADMIN)

        assert response.status_code == 200
        assert response.json()["state"] == "idle"

    def test_an_analyst_is_forbidden(self, client: TestClient) -> None:
        assert client.get(f"{_URL}/status", headers=_ANALYST).status_code == 403
