"""Seeds the two known accounts (Admin/Analyst) that replace the single
shared Builder bearer token (Unit 17a, MEADOWOPS-DOM-010, PRD 5.1/8.4
amendment, DD-22). Deliberately not wired into the app's lifespan — same
already-documented gap as seed_exception_rule_thresholds (no CLI seed
script exists yet in this project); run as a one-off script against the
shared dev DB, same as every prior unit's own seed data.

Idempotent by email (ON CONFLICT DO NOTHING) — running this again after a
row already exists is a no-op, not a password reset or rotation. A
configured *_password_hash takes precedence over the plaintext *_password
variant (security design review of this unit: the pre-hashed path is the
intended input in any deployed environment; plaintext is a documented
local-dev convenience only, the same tradeoff already accepted for
builder_token/DB credentials living in .env, PRD 8.4).
"""

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.password import hash_password
from app.db.auth import User
from app.db.enums import UserRole


def _resolve_password_hash(password: str | None, password_hash: str | None) -> str | None:
    if password_hash:
        return password_hash
    if password:
        return hash_password(password)
    return None


def seed_initial_users(session: Session, settings: Settings) -> None:
    rows = []

    admin_hash = _resolve_password_hash(
        settings.initial_admin_password, settings.initial_admin_password_hash
    )
    if settings.initial_admin_email and admin_hash:
        rows.append(
            {
                "email": settings.initial_admin_email.strip().lower(),
                "password_hash": admin_hash,
                "role": UserRole.ADMIN,
                "is_active": True,
            }
        )

    analyst_hash = _resolve_password_hash(
        settings.initial_analyst_password, settings.initial_analyst_password_hash
    )
    if settings.initial_analyst_email and analyst_hash:
        rows.append(
            {
                "email": settings.initial_analyst_email.strip().lower(),
                "password_hash": analyst_hash,
                "role": UserRole.ANALYST,
                "is_active": True,
            }
        )

    if not rows:
        return

    stmt = pg_insert(User).values(rows).on_conflict_do_nothing(index_elements=["email"])
    session.execute(stmt)
    session.commit()
