"""Shared test-only session-token minting (Unit 17a, MEADOWOPS-DOM-010).
Every api test file that used to construct `Settings(builder_token=...)`
and a matching `Authorization: Bearer <token>` header now does the same
thing against a real signed session token instead — minted directly via
app.core.security, not through a real login round-trip, since these tests
are exercising the routes' own auth *enforcement*, not the login endpoint
itself (that has its own tests/api/test_auth.py).
"""

from datetime import timedelta

from app.core.security import create_session_token

TEST_SESSION_SECRET = "test-session-secret-value-at-least-32-bytes-long"


def make_token(role: str, user_id: str = "test-user") -> str:
    return create_session_token(
        user_id=user_id, role=role, secret=TEST_SESSION_SECRET, expires_in=timedelta(hours=8)
    )
