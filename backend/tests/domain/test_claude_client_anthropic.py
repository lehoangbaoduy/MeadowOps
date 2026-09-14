"""Phase 4 blocker B3: app.domain.claude_client_anthropic.AnthropicClaudeClient
- the real Anthropic SDK adapter. Exercises it against the actual anthropic
package's own exception types (not hand-rolled stand-ins), since the whole
point of these tests is to pin real SDK behavior: the shape of
`message.content`, and - the one that matters most - that a raw upstream
error message (which can embed response body text) never reaches
ClaudeAPIError's own message, only the app's own logs. See
app.domain.scenario_generation.ScenarioGenerationFailedError's docstring for
why: app.api.admin_scenarios/app.api.chat forward str(exc) verbatim as an
HTTP 502 detail the Builder's browser sees.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic
import httpx2
import pytest

from app.domain.claude_client import ClaudeAPIError, ClaudeTimeoutError
from app.domain.claude_client_anthropic import AnthropicClaudeClient

_API_KEY = "sk-ant-test-key"


def _client() -> AnthropicClaudeClient:
    return AnthropicClaudeClient(api_key=_API_KEY, timeout_seconds=5.0)


def _fake_request() -> httpx2.Request:
    return httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _fake_response(status_code: int) -> httpx2.Response:
    return httpx2.Response(status_code, request=_fake_request())


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


class TestConstruction:
    def test_passes_timeout_and_max_retries_zero_to_the_sdk_client(self) -> None:
        # max_retries=0: scenario_generation/persona_chat/evaluation each
        # already implement PRD 9.2's own exactly-one-automatic-retry - the
        # SDK's own default internal retry would silently multiply that.
        with patch("app.domain.claude_client_anthropic.anthropic.Anthropic") as mock_ctor:
            AnthropicClaudeClient(api_key=_API_KEY, timeout_seconds=42.0)
        mock_ctor.assert_called_once_with(
            api_key=_API_KEY, timeout=42.0, max_retries=0
        )


class TestCreateMessageHappyPath:
    def test_joins_text_blocks_into_a_plain_string(self) -> None:
        client = _client()
        client._client = MagicMock()
        client._client.messages.create.return_value = SimpleNamespace(
            content=[_text_block("hello "), _text_block("world")],
            stop_reason="end_turn",
        )
        result = client.create_message(
            model="claude-test", system="s", messages=[], max_tokens=10
        )
        assert result.content == "hello world"
        assert result.stop_reason == "end_turn"

    def test_forwards_model_system_messages_max_tokens_verbatim(self) -> None:
        client = _client()
        client._client = MagicMock()
        client._client.messages.create.return_value = SimpleNamespace(
            content=[_text_block("ok")], stop_reason="end_turn"
        )
        messages = [{"role": "user", "content": "hi"}]
        client.create_message(
            model="claude-test", system="sys-prompt", messages=messages, max_tokens=512
        )
        client._client.messages.create.assert_called_once_with(
            model="claude-test", system="sys-prompt", messages=messages, max_tokens=512
        )

    def test_defaults_stop_reason_to_end_turn_when_the_sdk_returns_none(self) -> None:
        # Real API behavior on a normal completion - must not collapse a
        # real max_tokens stop_reason (the malformed-response path
        # scenario_generation/evaluation both depend on) into "end_turn"
        # via the wrong default order.
        client = _client()
        client._client = MagicMock()
        client._client.messages.create.return_value = SimpleNamespace(
            content=[_text_block("ok")], stop_reason=None
        )
        result = client.create_message(
            model="claude-test", system="s", messages=[], max_tokens=10
        )
        assert result.stop_reason == "end_turn"

    def test_preserves_a_real_non_end_turn_stop_reason(self) -> None:
        client = _client()
        client._client = MagicMock()
        client._client.messages.create.return_value = SimpleNamespace(
            content=[_text_block("truncat")], stop_reason="max_tokens"
        )
        result = client.create_message(
            model="claude-test", system="s", messages=[], max_tokens=10
        )
        assert result.stop_reason == "max_tokens"

    def test_ignores_non_text_content_blocks(self) -> None:
        client = _client()
        client._client = MagicMock()
        client._client.messages.create.return_value = SimpleNamespace(
            content=[
                _text_block("before "),
                SimpleNamespace(type="tool_use", id="t1"),
                _text_block("after"),
            ],
            stop_reason="end_turn",
        )
        result = client.create_message(
            model="claude-test", system="s", messages=[], max_tokens=10
        )
        assert result.content == "before after"

    def test_empty_content_list_yields_empty_string(self) -> None:
        client = _client()
        client._client = MagicMock()
        client._client.messages.create.return_value = SimpleNamespace(
            content=[], stop_reason="end_turn"
        )
        result = client.create_message(
            model="claude-test", system="s", messages=[], max_tokens=10
        )
        assert result.content == ""


class TestCreateMessageErrorMapping:
    def test_maps_api_timeout_error_to_claude_timeout_error(self) -> None:
        client = _client()
        client._client = MagicMock()
        client._client.messages.create.side_effect = anthropic.APITimeoutError(
            request=_fake_request()
        )
        with pytest.raises(ClaudeTimeoutError):
            client.create_message(model="m", system="s", messages=[], max_tokens=10)

    def test_claude_timeout_error_message_never_includes_raw_sdk_text(self) -> None:
        client = _client()
        client._client = MagicMock()
        client._client.messages.create.side_effect = anthropic.APITimeoutError(
            request=_fake_request()
        )
        with pytest.raises(ClaudeTimeoutError) as exc_info:
            client.create_message(model="m", system="s", messages=[], max_tokens=10)
        assert "docs.anthropic.com" not in str(exc_info.value)

    def test_maps_api_status_error_to_claude_api_error(self) -> None:
        client = _client()
        client._client = MagicMock()
        client._client.messages.create.side_effect = anthropic.RateLimitError(
            "rate limited", response=_fake_response(429), body=None
        )
        with pytest.raises(ClaudeAPIError):
            client.create_message(model="m", system="s", messages=[], max_tokens=10)

    def test_status_error_message_never_leaks_the_raw_upstream_body(self) -> None:
        # This is the finding scenario_generation.ScenarioGenerationFailedError's
        # own docstring flagged before this adapter existed: str(exc) on the
        # SDK's own exception embeds response body text, and this message
        # flows straight into an HTTP 502 detail reaching the Builder's
        # browser (app.api.admin_scenarios/app.api.chat).
        secret_upstream_text = "internal-trace-id-do-not-leak-9f3a"
        client = _client()
        client._client = MagicMock()
        client._client.messages.create.side_effect = anthropic.InternalServerError(
            f"Error code: 500 - {{'error': {{'message': '{secret_upstream_text}'}}}}",
            response=_fake_response(500),
            body=None,
        )
        with pytest.raises(ClaudeAPIError) as exc_info:
            client.create_message(model="m", system="s", messages=[], max_tokens=10)
        assert secret_upstream_text not in str(exc_info.value)
        assert "500" in str(exc_info.value)

    def test_maps_generic_api_connection_error_to_claude_api_error(self) -> None:
        client = _client()
        client._client = MagicMock()
        client._client.messages.create.side_effect = anthropic.APIConnectionError(
            request=_fake_request()
        )
        with pytest.raises(ClaudeAPIError):
            client.create_message(model="m", system="s", messages=[], max_tokens=10)


class TestMarkdownFenceStripping:
    """Found live, not hypothetically: claude-sonnet-4-5 wraps JSON
    responses in a ```json fence despite every prompt's own "no markdown
    fences" instruction. MockClaudeClient never exercised this shape, so
    none of this adapter's other tests (or the 23 written before a real key
    existed) caught it - scenario_generation/persona_chat/evaluation's
    parse_*_response functions all call json.loads directly on
    ClaudeResponse.content."""

    def test_strips_a_json_tagged_fence(self) -> None:
        client = _client()
        client._client = MagicMock()
        client._client.messages.create.return_value = SimpleNamespace(
            content=[_text_block('```json\n{"a": 1}\n```')], stop_reason="end_turn"
        )
        result = client.create_message(
            model="m", system="s", messages=[], max_tokens=10
        )
        assert result.content == '{"a": 1}'

    def test_strips_a_bare_fence(self) -> None:
        client = _client()
        client._client = MagicMock()
        client._client.messages.create.return_value = SimpleNamespace(
            content=[_text_block('```\n{"a": 1}\n```')], stop_reason="end_turn"
        )
        result = client.create_message(
            model="m", system="s", messages=[], max_tokens=10
        )
        assert result.content == '{"a": 1}'

    def test_passes_unfenced_content_through_unchanged(self) -> None:
        client = _client()
        client._client = MagicMock()
        client._client.messages.create.return_value = SimpleNamespace(
            content=[_text_block('{"a": 1}')], stop_reason="end_turn"
        )
        result = client.create_message(
            model="m", system="s", messages=[], max_tokens=10
        )
        assert result.content == '{"a": 1}'

    def test_does_not_strip_content_that_merely_contains_backticks(self) -> None:
        # Conservative by design - only a fence wrapping the *entire*
        # response is stripped, so a legitimate response that happens to
        # mention a code sample mid-text isn't corrupted.
        client = _client()
        client._client = MagicMock()
        content = 'Here is some text with ```inline code``` in the middle.'
        client._client.messages.create.return_value = SimpleNamespace(
            content=[_text_block(content)], stop_reason="end_turn"
        )
        result = client.create_message(
            model="m", system="s", messages=[], max_tokens=10
        )
        assert result.content == content
