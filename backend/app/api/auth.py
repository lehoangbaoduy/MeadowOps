"""Unit 17a (MEADOWOPS-DOM-010): `POST /api/v1/auth/login` — validates
email + password against `live.user` (argon2) and issues a signed session
token (app.core.security) declaring the caller's role, replacing Unit 6's
single shared Builder bearer token (PRD 5.1/8.4 amendment, DD-22).

Rate limited per-email (app.core.rate_limit.LoginRateLimiter, one instance
per app in app.state.login_rate_limiter) — security design review of this
unit: switching from a random high-entropy token to human-chosen passwords
against two predictable email addresses makes online credential-guessing a
real threat that didn't exist before.

Unknown email, wrong password, and an inactive account all return the same
generic 401 (never revealing which case occurred — account enumeration),
and always run one argon2 verify regardless of whether the email exists
(against a fixed dummy hash when it doesn't) so a missing account isn't
also distinguishable by response time.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.password import hash_password, verify_password
from app.core.security import create_session_token
from app.db.auth import User
from app.db.session import get_session

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_GENERIC_INVALID_CREDENTIALS = "Invalid credentials"
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-timing-parity")


class LoginRequest(BaseModel):
    # Bounded (not just `str`): `email` becomes the rate limiter's dict key
    # before any DB lookup validates it (app.core.rate_limit), and `password`
    # is fed straight to argon2 — an unbounded body lets one request grow
    # the limiter's memory or burn CPU disproportionately to its size.
    # 254 is RFC 5321's own max mailbox length; 256 gives password headroom
    # over any real passphrase without capping it uncomfortably.
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class LoginResponse(BaseModel):
    access_token: str
    role: str


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, session: Session = Depends(get_session)) -> LoginResponse:
    email = payload.email.strip().lower()

    limiter = request.app.state.login_rate_limiter
    if not limiter.check_and_record(email):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts, try again later",
        )

    user = session.scalar(select(User).where(User.email == email))
    hash_to_check = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_ok = verify_password(payload.password, hash_to_check)

    if user is None or not user.is_active or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_GENERIC_INVALID_CREDENTIALS
        )

    limiter.reset(email)
    settings = request.app.state.settings
    token = create_session_token(
        user_id=str(user.id),
        role=user.role.value,
        secret=settings.session_secret_key,
        expires_in=timedelta(hours=settings.session_token_exp_hours),
    )
    return LoginResponse(access_token=token, role=user.role.value)
