"""PRD line 373: "Claude API call/response handling (mocked for
deterministic tests, plus periodic live-call smoke tests)". This is that
smoke test - a genuine round trip through AnthropicClaudeClient to the real
Anthropic API, not a MockClaudeClient/mocked-transport stand-in.

Skipped unless explicitly opted into via MEADOWOPS_RUN_LIVE_CLAUDE_SMOKE_TEST
=1 - never runs as part of a normal `pytest -q` invocation (local, CI, or
this repo's own backend-ci.yml), even though tests/conftest.py's
load_dotenv() puts a real ANTHROPIC_API_KEY into every test process's
environment. A real key being present must never be enough on its own to
make a test suite start spending money on live API calls - same reasoning
as Settings.claude_client_enabled itself (app/core/config.py).
"""

from __future__ import annotations

import os

import pytest

from app.core.config import Settings
from app.domain.claude_client_anthropic import AnthropicClaudeClient

pytestmark = pytest.mark.skipif(
    os.environ.get("MEADOWOPS_RUN_LIVE_CLAUDE_SMOKE_TEST") != "1",
    reason="live Claude API smoke test - opt in via MEADOWOPS_RUN_LIVE_CLAUDE_SMOKE_TEST=1",
)


def test_live_round_trip_against_the_real_anthropic_api() -> None:
    settings = Settings(
        session_secret_key="x" * 32,
        internal_service_token="x" * 32,
    )
    assert settings.anthropic_api_key is not None, (
        "ANTHROPIC_API_KEY must be set in the environment to run this smoke test"
    )
    client = AnthropicClaudeClient(
        api_key=settings.anthropic_api_key.get_secret_value(), timeout_seconds=30.0
    )

    result = client.create_message(
        model="claude-sonnet-4-5",
        system="Reply with exactly one word: the word 'pong'.",
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=16,
    )

    assert "pong" in result.content.lower()
    assert result.stop_reason == "end_turn"
