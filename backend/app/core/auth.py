import hmac

from fastapi import Depends, Header, HTTPException, Request, status

from app.core.security import InvalidSessionToken, decode_session_token

# Unit 20 (MEADOWOPS-API-004, DD-2): the identity require_authenticated
# returns for Subsystem 2's internal service credential. Deliberately not a
# UUID - no `live.user` row backs it, so any route that ever tried to FK it
# (there are none today) fails cleanly rather than looking like a real user.
INTERNAL_SERVICE_USER_ID = "subsystem2-internal"


def require_authenticated(
    request: Request, authorization: str | None = Header(default=None)
) -> dict[str, str]:
    """Unit 17a (MEADOWOPS-DOM-010, PRD 5.1/8.4 amendment): replaces the
    single shared Builder bearer token. Decodes and verifies the signed
    session token (app.core.security) issued at login by app.api.auth —
    any valid, non-expired token for either role passes here, since Admin
    and Analyst both get read access to everything Subsystem 1 exposes.
    require_admin (below) is the write-gating layer, built on top of this
    one rather than reimplementing verification — security design review of
    this unit: divergent verification code between two dependencies is how
    one of them quietly ends up missing an expiry or algorithm check.

    Unit 20 (MEADOWOPS-API-004, DD-2): also accepts Subsystem 2's internal
    service credential (Settings.internal_service_token) as an alternate
    valid Bearer value, checked first via a constant-time comparison on
    UTF-8-encoded bytes on both sides - `hmac.compare_digest`'s `str`
    overload raises `TypeError` (not `False`) on non-ASCII input, the exact
    HIGH Unit 6's own security review found in the original builder_token
    check, so this deliberately doesn't repeat it. Matching short-circuits
    before any JWT decoding is attempted and returns role="service" -
    require_admin (below) already 403s that role via its existing check, and
    Query Playground's routes explicitly opt out via reject_service_role
    (app.api.query_playground) rather than relying on this credential's
    non-UUID user_id to fail incidentally deep in a route body - security
    review of this unit found that ordering hole before it shipped."""
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )
    token = authorization.removeprefix("Bearer ")
    settings = request.app.state.settings
    if hmac.compare_digest(
        token.encode("utf-8"), settings.internal_service_token.encode("utf-8")
    ):
        return {"user_id": INTERNAL_SERVICE_USER_ID, "role": "service"}
    try:
        claims = decode_session_token(token, secret=settings.session_secret_key)
    except InvalidSessionToken as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        ) from exc
    return {"user_id": claims["sub"], "role": claims["role"]}


def require_admin(identity: dict[str, str] = Depends(require_authenticated)) -> dict[str, str]:
    """Write-gating dependency for master data and every other admin panel
    control (PRD 8.4). A valid Analyst token is authenticated but not
    authorized here — 403, not 401, since the credential itself is fine.
    role="service" (Unit 20's internal credential) is rejected here too,
    with no extra code - it's just never "admin"."""
    if identity["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required"
        )
    return identity


def reject_service_role(
    identity: dict[str, str] = Depends(require_authenticated),
) -> dict[str, str]:
    """Unit 20 (MEADOWOPS-API-004): explicit opt-out for require_authenticated
    routes that do more than a pure read - the Query Playground can execute
    and commit arbitrary confirmed SQL, or refresh the sandbox schema as the
    owner role (app.api.query_playground), before a route body ever gets far
    enough to notice the internal-service credential's non-UUID user_id.
    Pre-implementation security review of this unit found that relying on
    that UUID-parse side effect as a backstop was an accident of each
    route's own argument-evaluation order, not a real authorization
    boundary - this closes it structurally instead, as a FastAPI dependency
    that runs before the route body regardless of what that body does.
    Passes any real human identity (admin or analyst) through unchanged."""
    if identity["role"] == "service":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Internal service credential cannot access this route",
        )
    return identity


def require_analyst(identity: dict[str, str] = Depends(reject_service_role)) -> dict[str, str]:
    """Unit 30c (MEADOWOPS-UI-005, S1-FR-15/PRD 347/380): write-gating
    dependency for the one Analyst-only write this app has - uploading a
    chat attachment. Built on reject_service_role (not require_authenticated
    directly) so role="service" 403s with reject_service_role's own clear
    "internal service credential" message and, just as importantly, so
    tests/architecture/test_subsystem_boundary.py's static dependency-graph
    classifier (which only recognizes require_admin/reject_service_role/
    require_authenticated) correctly buckets every route built on this one
    as "service_rejected" - the same bucket every other chat route is in -
    instead of falling through to "service_allowed" by accident of not
    calling reject_service_role explicitly. Mirrors require_admin's own
    shape otherwise (403, not 401, for a validly-authenticated Admin token).
    PRD 8.4/380 frame file attachments as Analyst-side specifically
    (S1-FR-15's own wording), not a capability either role gets - the
    asymmetry is deliberate, not an oversight to fix later."""
    if identity["role"] != "analyst":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Analyst role required"
        )
    return identity
