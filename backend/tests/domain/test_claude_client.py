"""RED-first tests for the mocked Claude client (spec MEADOWOPS-INFRA-003,
PRD line 373: "Claude API call/response handling (mocked for deterministic
tests, plus periodic live-call smoke tests)").

The point of this mock is programmable *failure*, not just canned success -
a mock that only ever returns a fixed happy-path string is a tautology.
PRD 9.2 (line 411) requires a timeout/API error path; PRD 6.8/9.2 (line 413)
requires a malformed/incomplete-response path. Both must be scriptable here
so Phase 3's retry (U22/U25) and schema-validation (U25) logic has something
real to be tested against later. The retry/validation logic itself is out
of scope for this unit.
"""

from __future__ import annotations

import pytest

from app.domain.claude_client import (
    ClaudeAPIError,
    ClaudeClient,
    ClaudeResponse,
    ClaudeTimeoutError,
    MockClaudeClient,
)

MODEL = "claude-test-model"


class TestClaudeResponse:
    def test_defaults_stop_reason_to_end_turn(self):
        response = ClaudeResponse(content="hello")
        assert response.stop_reason == "end_turn"


class TestMockClaudeClientHappyPath:
    def test_returns_the_scripted_response(self):
        client = MockClaudeClient(script=[ClaudeResponse(content="scenario text")])
        result = client.create_message(
            model=MODEL,
            system="you are a scenario generator",
            messages=[{"role": "user", "content": "generate one"}],
            max_tokens=1024,
        )
        assert result.content == "scenario text"

    def test_pops_scripted_responses_in_order_across_calls(self):
        client = MockClaudeClient(
            script=[ClaudeResponse(content="first"), ClaudeResponse(content="second")]
        )
        first = client.create_message(
            model=MODEL, system="s", messages=[], max_tokens=10
        )
        second = client.create_message(
            model=MODEL, system="s", messages=[], max_tokens=10
        )
        assert (first.content, second.content) == ("first", "second")

    def test_records_every_call_in_call_log(self):
        client = MockClaudeClient(script=[ClaudeResponse(content="ok")])
        client.create_message(
            model=MODEL,
            system="sys-prompt",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=512,
        )
        assert len(client.call_log) == 1
        assert client.call_log[0]["model"] == MODEL
        assert client.call_log[0]["system"] == "sys-prompt"
        assert client.call_log[0]["max_tokens"] == 512
        assert client.call_log[0]["messages"] == [{"role": "user", "content": "hi"}]

    def test_call_log_messages_are_isolated_from_caller_appending_after_the_call(self):
        # list(messages) is a shallow copy: it isolates the logged entry from a
        # caller appending a new turn to the same list object (the realistic
        # retry/conversation-loop pattern) but not from mutating an existing
        # message dict in place - that would need a deep copy, not needed here.
        client = MockClaudeClient(script=[ClaudeResponse(content="ok")])
        messages = [{"role": "user", "content": "hi"}]
        client.create_message(model=MODEL, system="s", messages=messages, max_tokens=10)
        messages.append({"role": "assistant", "content": "reply"})
        assert client.call_log[0]["messages"] == [{"role": "user", "content": "hi"}]

    def test_raises_claude_api_error_when_script_exhausted(self):
        client = MockClaudeClient(script=[])
        with pytest.raises(ClaudeAPIError):
            client.create_message(model=MODEL, system="s", messages=[], max_tokens=10)


class TestMockClaudeClientScriptIsolation:
    def test_a_shared_script_list_is_not_drained_across_instances(self):
        shared_script = [ClaudeResponse(content="a"), ClaudeResponse(content="b")]
        first_client = MockClaudeClient(script=shared_script)
        first_client.create_message(model=MODEL, system="s", messages=[], max_tokens=10)
        second_client = MockClaudeClient(script=shared_script)
        result = second_client.create_message(
            model=MODEL, system="s", messages=[], max_tokens=10
        )
        assert result.content == "a"


class TestMockClaudeClientFailureScripting:
    def test_can_be_scripted_to_raise_timeout_error(self):
        client = MockClaudeClient(script=[ClaudeTimeoutError("simulated timeout")])
        with pytest.raises(ClaudeTimeoutError):
            client.create_message(model=MODEL, system="s", messages=[], max_tokens=10)

    def test_can_be_scripted_to_raise_generic_api_error(self):
        client = MockClaudeClient(script=[ClaudeAPIError("simulated 500")])
        with pytest.raises(ClaudeAPIError):
            client.create_message(model=MODEL, system="s", messages=[], max_tokens=10)

    def test_a_scripted_failure_is_still_recorded_in_the_call_log(self):
        client = MockClaudeClient(script=[ClaudeTimeoutError("simulated timeout")])
        with pytest.raises(ClaudeTimeoutError):
            client.create_message(model=MODEL, system="s", messages=[], max_tokens=10)
        assert len(client.call_log) == 1

    def test_can_return_a_malformed_or_incomplete_response_without_raising(self):
        malformed = ClaudeResponse(content="{incomplete json", stop_reason="max_tokens")
        client = MockClaudeClient(script=[malformed])
        result = client.create_message(model=MODEL, system="s", messages=[], max_tokens=10)
        assert result.stop_reason == "max_tokens"
        assert result.content == "{incomplete json"


class TestClaudeTimeoutErrorIsAClaudeAPIError:
    def test_subclass_relationship(self):
        assert issubclass(ClaudeTimeoutError, ClaudeAPIError)


class TestMockClaudeClientSatisfiesProtocol:
    def test_isinstance_check_against_runtime_checkable_protocol(self):
        client = MockClaudeClient(script=[ClaudeResponse(content="ok")])
        assert isinstance(client, ClaudeClient)
