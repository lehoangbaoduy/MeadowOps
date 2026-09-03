"""Unit 17a (MEADOWOPS-DOM-010): signed session tokens (JWT/HS256) issued at
login and verified on every request by require_authenticated/require_admin.
Security design review of this unit: algorithms must be pinned explicitly
in the decode call (never trust the token's own `alg` header — the classic
alg-confusion class of bug), and exp must be short since this is a
stateless scheme with no server-side revocation (logout/is_active flips
don't invalidate an outstanding token before it expires — secret rotation
is the only forced-revocation lever, documented in the PRD amendment/DD-22).
"""

from datetime import timedelta

import jwt
import pytest

from app.core.security import (
    InvalidSessionToken,
    create_session_token,
    decode_session_token,
)

_SECRET = "test-session-secret-value"


def test_create_then_decode_round_trips_the_claims() -> None:
    token = create_session_token(
        user_id="11111111-1111-1111-1111-111111111111",
        role="admin",
        secret=_SECRET,
        expires_in=timedelta(hours=8),
    )
    claims = decode_session_token(token, secret=_SECRET)
    assert claims["sub"] == "11111111-1111-1111-1111-111111111111"
    assert claims["role"] == "admin"


def test_decode_rejects_a_token_signed_with_a_different_secret() -> None:
    token = create_session_token(
        user_id="u1", role="analyst", secret=_SECRET, expires_in=timedelta(hours=8)
    )
    with pytest.raises(InvalidSessionToken):
        decode_session_token(token, secret="a-different-secret-entirely")


def test_decode_rejects_an_expired_token() -> None:
    token = create_session_token(
        user_id="u1", role="analyst", secret=_SECRET, expires_in=timedelta(seconds=-1)
    )
    with pytest.raises(InvalidSessionToken):
        decode_session_token(token, secret=_SECRET)


def test_decode_rejects_garbage_input() -> None:
    with pytest.raises(InvalidSessionToken):
        decode_session_token("not-a-jwt-at-all", secret=_SECRET)


def test_decode_rejects_a_token_signed_with_the_none_algorithm() -> None:
    # The classic alg-confusion attack: a token whose header claims
    # alg=none and carries no signature at all. decode_session_token must
    # pin algorithms=["HS256"] explicitly rather than trusting the header.
    forged = jwt.encode({"sub": "attacker", "role": "admin"}, key=None, algorithm="none")
    with pytest.raises(InvalidSessionToken):
        decode_session_token(forged, secret=_SECRET)
