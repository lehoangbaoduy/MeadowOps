"""Phase 4 blocker B3: app.main.create_app wires app.state.claude_client
from Settings.claude_client_enabled - was hardcoded to None unconditionally
before this unit (see git history for app/main.py's own prior comment).
Every existing 503 caller path (app.api.admin_scenarios/app.api.chat) is
covered by their own existing tests asserting the None/disabled case; this
file is specifically about create_app's own wiring decision, not the
routes built on top of it.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.claude_client_anthropic import AnthropicClaudeClient
from app.main import create_app
from tests.support.auth import TEST_SESSION_SECRET

_SERVICE_TOKEN = "test-internal-service-token-value-at-least-32-bytes-long"


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "session_secret_key": TEST_SESSION_SECRET,
        "internal_service_token": _SERVICE_TOKEN,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class TestClaudeClientWiring:
    def test_disabled_by_default_leaves_claude_client_none(self) -> None:
        app = create_app(_settings())
        assert app.state.claude_client is None

    def test_enabled_constructs_a_real_anthropic_claude_client(self) -> None:
        app = create_app(
            _settings(claude_client_enabled=True, anthropic_api_key="sk-ant-test-key")
        )
        assert isinstance(app.state.claude_client, AnthropicClaudeClient)

    def test_health_route_still_works_regardless_of_claude_client_state(self) -> None:
        # Constructing the real anthropic.Anthropic client must not itself
        # make a network call or otherwise break app startup.
        app = create_app(
            _settings(claude_client_enabled=True, anthropic_api_key="sk-ant-test-key")
        )
        client = TestClient(app)
        assert client.get("/health").status_code == 200
