import hmac

from fastapi import Header, HTTPException, Request, status


def require_builder(
    request: Request, authorization: str | None = Header(default=None)
) -> dict[str, str]:
    """PRD 8.4: restrict admin operations to the Builder. Deliberately a
    single shared bearer token, not a full identity system — PRD 5.1 puts
    auth/multi-tenant complexity beyond two users out of scope, and the
    Analyst's own access doesn't begin until Active Use (PRD Section 11).
    `hmac.compare_digest` avoids a timing side-channel on the comparison —
    called on `bytes`, not `str`: CPython's `str` overload only takes the
    constant-time path when both operands are pure ASCII and otherwise
    raises TypeError, so any non-ASCII byte in the Authorization header
    (Starlette decodes header values as latin-1, so any byte >= 0x80
    survives) would 500 an unauthenticated request instead of 401ing it
    (security review of this unit, reproduced empirically). The encoding
    used here is arbitrary — both operands go through the same one, and a
    mismatched decode of the true token can only produce a non-match,
    never a false accept."""
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )
    token = authorization.removeprefix("Bearer ")
    expected = request.app.state.settings.builder_token
    if not hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return {"role": "builder"}
