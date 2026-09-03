"""Unit 17a (MEADOWOPS-DOM-010): seeding the two known accounts that
replace the single shared Builder bearer token. Still just two known
users — no self-registration path exists anywhere; this is the only way a
`live.user` row is ever created.
"""

import os
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.password import hash_password, verify_password
from app.db.auth import User
from app.db.enums import UserRole
from app.services.auth_seed import seed_initial_users

_ADMIN_EMAIL = "zztest-admin@meadowops.local"
_ANALYST_EMAIL = "zztest-analyst@meadowops.local"


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture(autouse=True)
def _cleanup(db_session: Session) -> Generator[None, None, None]:
    yield
    db_session.execute(delete(User).where(User.email.in_([_ADMIN_EMAIL, _ANALYST_EMAIL])))
    db_session.commit()


def _settings(**overrides: str) -> Settings:
    base = {
        "session_secret_key": "test-session-secret-value-at-least-32-bytes",
        "database_url": os.environ["MEADOWOPS_DATABASE_URL"],
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


def test_seeds_admin_and_analyst_from_plaintext_passwords(db_session: Session) -> None:
    settings = _settings(
        initial_admin_email=_ADMIN_EMAIL,
        initial_admin_password="admin-plaintext-password",
        initial_analyst_email=_ANALYST_EMAIL,
        initial_analyst_password="analyst-plaintext-password",
    )
    seed_initial_users(db_session, settings)

    admin = db_session.query(User).filter_by(email=_ADMIN_EMAIL).one()
    assert admin.role == UserRole.ADMIN
    assert admin.is_active is True
    assert verify_password("admin-plaintext-password", admin.password_hash)

    analyst = db_session.query(User).filter_by(email=_ANALYST_EMAIL).one()
    assert analyst.role == UserRole.ANALYST
    assert verify_password("analyst-plaintext-password", analyst.password_hash)


def test_prefers_the_pre_hashed_password_over_plaintext(db_session: Session) -> None:
    real_hash = hash_password("the-real-password")
    settings = _settings(
        initial_admin_email=_ADMIN_EMAIL,
        initial_admin_password="this-should-be-ignored",
        initial_admin_password_hash=real_hash,
    )
    seed_initial_users(db_session, settings)

    admin = db_session.query(User).filter_by(email=_ADMIN_EMAIL).one()
    assert admin.password_hash == real_hash


def test_email_is_stored_lowercased(db_session: Session) -> None:
    settings = _settings(
        initial_admin_email="ZzTest-Admin@MeadowOps.LOCAL",
        initial_admin_password="admin-plaintext-password",
    )
    seed_initial_users(db_session, settings)

    admin = db_session.query(User).filter_by(email=_ADMIN_EMAIL).one_or_none()
    assert admin is not None


def test_is_idempotent_and_does_not_reset_an_existing_password(db_session: Session) -> None:
    settings = _settings(
        initial_admin_email=_ADMIN_EMAIL, initial_admin_password="first-password"
    )
    seed_initial_users(db_session, settings)
    first_hash = db_session.query(User).filter_by(email=_ADMIN_EMAIL).one().password_hash

    settings_again = _settings(
        initial_admin_email=_ADMIN_EMAIL, initial_admin_password="a-different-password"
    )
    seed_initial_users(db_session, settings_again)
    second_hash = db_session.query(User).filter_by(email=_ADMIN_EMAIL).one().password_hash

    assert first_hash == second_hash


def test_skips_a_role_with_no_email_or_password_configured(db_session: Session) -> None:
    settings = _settings()
    seed_initial_users(db_session, settings)  # must not raise
    assert db_session.query(User).filter_by(email=_ADMIN_EMAIL).one_or_none() is None
