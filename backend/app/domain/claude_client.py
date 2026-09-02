"""Mocked Claude client (spec MEADOWOPS-INFRA-003, PRD line 373: "Claude
API call/response handling (mocked for deterministic tests, plus periodic
live-call smoke tests)").

`ClaudeClient` is a Protocol mirroring the real Anthropic Messages API call
shape (model/system/messages/max_tokens in, content/stop_reason out, per
the anthropic-sdk-python `client.messages.create()` signature and `Message`
response), so a real adapter can satisfy it later without changing any
caller. `MockClaudeClient` is the only implementation built at this unit:
scriptable to return a normal response, raise an API error/timeout (PRD 9.2
line 411), or return a malformed/incomplete response (PRD 6.8/9.2 line 413)
- the three cases Phase 3's retry (U22/U25) and schema-validation (U25)
logic will be tested against. That retry/validation logic itself, and the
`anthropic` SDK dependency a real adapter would need, are out of scope
here - nothing in this module makes a live API call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class ClaudeAPIError(Exception):
    """A non-timeout Claude API failure (rate limit, 5xx, malformed transport)."""


class ClaudeTimeoutError(ClaudeAPIError):
    """A Claude API call that timed out (PRD 9.2 line 411)."""


@dataclass(frozen=True)
class ClaudeResponse:
    content: str
    stop_reason: str = "end_turn"


@runtime_checkable
class ClaudeClient(Protocol):
    def create_message(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> ClaudeResponse: ...


@dataclass
class MockClaudeClient:
    script: list[ClaudeResponse | Exception] = field(default_factory=list)
    call_log: list[dict[str, object]] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        # Copy: a caller must be able to reuse the same script list across
        # multiple MockClaudeClient instances without one instance's pop(0)
        # draining the other's script (the same aliasing class fixed below
        # for `messages`, applied to this field too).
        self.script = list(self.script)

    def create_message(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> ClaudeResponse:
        # Shallow-copy messages: isolates the logged entry from a caller that
        # appends a new turn to the same list object across calls (a retry/
        # conversation loop) - the realistic reuse pattern. Does not protect
        # against mutating an existing message dict in place; not needed here.
        self.call_log.append(
            {
                "model": model,
                "system": system,
                "messages": list(messages),
                "max_tokens": max_tokens,
            }
        )
        if not self.script:
            raise ClaudeAPIError(
                "MockClaudeClient.script exhausted with no response queued"
            )
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
