"""Real Anthropic SDK adapter for `ClaudeClient` (Phase 4, blocker B3).

Constructed only when `app.core.config.Settings.claude_client_enabled` is
True (its own model_validator enforces `anthropic_api_key` is then present)
- `app.main.create_app` wires this in; absent, `app.state.claude_client`
stays None and every existing 503 caller path (app.api.admin_scenarios,
app.api.chat) is unchanged. Satisfies `app.domain.claude_client.ClaudeClient`'s
Protocol exactly - same model/system/messages/max_tokens in, same
`ClaudeResponse(content, stop_reason)` out - so scenario_generation/
persona_chat/evaluation need no changes to call a live model instead of
`MockClaudeClient`.

Three things this module does deliberately, both flagged by review comments
written before this adapter existed plus one found empirically once a real
key was configured:

1. A bounded per-call timeout, passed to the SDK client itself rather than
   left to the caller - `ClaudeClient`'s own Protocol docstring: every real
   caller holds its DB session's connection open across the call. The other
   remedy that docstring names (restructuring callers to release the
   connection before calling out) is a separate, more invasive change and
   stays open.
2. `max_retries=0` - scenario_generation/persona_chat/evaluation each
   already implement PRD 9.2's "exactly one automatic retry" themselves.
   The SDK's own default internal retry (on 429/5xx/connection errors)
   would silently turn one logical call into several HTTP requests
   underneath that, undermining the PRD-mandated retry count.
3. Markdown-code-fence stripping - found live: despite every prompt's own
   "no markdown fences" instruction, claude-sonnet-4-5 routinely wraps its
   JSON response in a ```json ... ``` fence anyway. `MockClaudeClient`
   never exercised this shape, so it reached none of the 23 tests written
   before a real key existed. Every one of scenario_generation/
   persona_chat/evaluation's own `parse_*_response` functions calls
   `json.loads` directly on `ClaudeResponse.content` - fixed once, here,
   rather than in each of the three, since this is a real-API response
   quirk the domain layer should never need to know about.
"""

from __future__ import annotations

import logging

import anthropic

from app.domain.claude_client import ClaudeAPIError, ClaudeResponse, ClaudeTimeoutError

logger = logging.getLogger(__name__)


def _strip_markdown_json_fence(content: str) -> str:
    """Undo a ```json ... ``` (or bare ``` ... ```) fence wrapping the
    *entire* response - found live, not hypothetically (see module
    docstring). Deliberately conservative: only strips when the whole
    stripped content both starts and ends with a fence line, so a response
    that merely contains a backtick or code sample mid-text is returned
    unchanged rather than corrupted."""
    stripped = content.strip()
    if not stripped.startswith("```"):
        return content
    lines = stripped.splitlines()
    if len(lines) < 2 or lines[-1].strip() != "```":
        return content
    return "\n".join(lines[1:-1])


class AnthropicClaudeClient:
    def __init__(self, *, api_key: str, timeout_seconds: float) -> None:
        self._client = anthropic.Anthropic(
            api_key=api_key, timeout=timeout_seconds, max_retries=0
        )

    def create_message(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> ClaudeResponse:
        try:
            message = self._client.messages.create(
                model=model,
                system=system,
                messages=messages,
                max_tokens=max_tokens,
            )
        except anthropic.APITimeoutError as exc:
            logger.warning("Claude API call timed out", exc_info=exc)
            raise ClaudeTimeoutError("Claude API request timed out") from exc
        except anthropic.APIStatusError as exc:
            # scenario_generation.ScenarioGenerationFailedError's own
            # docstring (written before this adapter existed) flags exactly
            # this: str(exc) on the SDK's own exception embeds the raw
            # upstream response body, and that string flows straight into an
            # HTTP 502 detail the Builder's browser sees
            # (app.api.admin_scenarios/app.api.chat forward str(exc)
            # verbatim). Log the real exception server-side only; raise a
            # generic, status-code-only message.
            logger.warning(
                "Claude API returned an error status",
                exc_info=exc,
                extra={"status_code": exc.status_code},
            )
            raise ClaudeAPIError(
                f"Claude API request failed (status {exc.status_code})"
            ) from exc
        except anthropic.APIError as exc:
            logger.warning("Claude API call failed", exc_info=exc)
            raise ClaudeAPIError("Claude API request failed") from exc

        content = "".join(
            block.text for block in message.content if block.type == "text"
        )
        content = _strip_markdown_json_fence(content)
        return ClaudeResponse(
            content=content, stop_reason=message.stop_reason or "end_turn"
        )
