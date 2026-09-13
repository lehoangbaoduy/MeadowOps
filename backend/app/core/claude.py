"""Shared FastAPI dependency for reaching `app.state.claude_client`.

Originally a private function inside app.api.admin_scenarios (Unit 22) -
promoted here at Unit 23 once app.api.chat needed the exact same
dependency (`app.state.claude_client` is `None` until a real Anthropic SDK
adapter is wired in, Phase 4, blocker B3). A second real caller is what
justifies the extraction (DRY, not speculative) - both routers now import
this instead of keeping their own copy.
"""

from fastapi import Request

from app.domain.claude_client import ClaudeClient


def get_claude_client(request: Request) -> ClaudeClient | None:
    return request.app.state.claude_client
