"""Signed session tokens (Unit 17a, MEADOWOPS-DOM-010) — JWT/HS256, issued
by app/api/auth.py's login endpoint, verified by app/core/auth.py's
require_authenticated on every request.

Security design review of this unit: `algorithms` is pinned explicitly to
["HS256"] in the decode call, never inferred from the token's own header —
otherwise a forged token claiming alg="none" (or a mismatched asymmetric
algorithm) could bypass signature verification entirely (the classic
alg-confusion class of bug). Stateless by design: no server-side session
store, consistent with "still just two known users, not a full identity
system" (PRD 5.1 amendment). This means logout and flipping a user's
is_active to False do NOT invalidate an already-issued token before its own
`exp` — accepted explicitly (security design review of this unit) on the
condition that `exp` stays short (hours, not days); the only forced
revocation lever for a compromised token is rotating session_secret_key,
which logs out both users at once.
"""

from datetime import UTC, datetime, timedelta
from typing import TypedDict

import jwt

_ALGORITHM = "HS256"


class SessionClaims(TypedDict):
    sub: str
    role: str
    exp: int


class InvalidSessionToken(Exception):
    """Raised for any decode failure — expired, wrong secret, wrong
    algorithm, or malformed input. Callers (require_authenticated) map this
    uniformly to a 401, never distinguishing the reason in the response."""


def create_session_token(*, user_id: str, role: str, secret: str, expires_in: timedelta) -> str:
    now = datetime.now(UTC)
    payload = {"sub": user_id, "role": role, "iat": now, "exp": now + expires_in}
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def decode_session_token(token: str, *, secret: str) -> SessionClaims:
    try:
        claims = jwt.decode(token, secret, algorithms=[_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise InvalidSessionToken(str(exc)) from exc
    if "sub" not in claims or "role" not in claims:
        raise InvalidSessionToken("Missing required claims")
    return claims  # type: ignore[return-value]
