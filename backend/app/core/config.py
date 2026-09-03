from psycopg.conninfo import make_conninfo
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    """No module-level singleton — `create_app(settings=...)` constructs one
    per call, so tests can monkeypatch/override cleanly instead of fighting
    an import-time-cached global."""

    model_config = SettingsConfigDict(env_prefix="MEADOWOPS_", extra="ignore")

    # Unit 17a (MEADOWOPS-DOM-010, DD-22): replaces the single shared
    # builder_token. min_length=32 matches RFC 7518 3.2's recommended
    # minimum HMAC key length for HS256 (PyJWT warns below it).
    session_secret_key: str = Field(min_length=32)
    session_token_exp_hours: int = Field(default=8, gt=0)
    # Security design review of this unit: per-email, not per-IP — every
    # browser login attempt reaches FastAPI via the same Next.js
    # server-side proxy, so a per-IP bucket would collapse into one shared
    # limit across both real users.
    login_rate_limit_max_attempts: int = Field(default=5, gt=0)
    login_rate_limit_window_seconds: int = Field(default=900, gt=0)
    # Seeding the two known accounts (app.services.auth_seed): a pre-hashed
    # password is the primary path; the plaintext variant is a documented
    # local-dev convenience only (security design review of this unit — a
    # human-chosen password is a different risk class than the random
    # builder_token this replaces, since it may be reused elsewhere).
    initial_admin_email: str | None = None
    initial_admin_password: str | None = None
    initial_admin_password_hash: str | None = None
    initial_analyst_email: str | None = None
    initial_analyst_password: str | None = None
    initial_analyst_password_hash: str | None = None
    # DD-11: Settings stays authoritative only for values the FastAPI app
    # process itself consumes. Unit 8 is the first unit where the app opens
    # its own DB connection (admin CRUD), so database_url joins the auth
    # settings above here — everything upstream of the app (migrations,
    # seeders, test fixtures) keeps reading MEADOWOPS_DATABASE_URL via plain
    # os.environ.
    database_url: str = Field(min_length=1)
    # Unit 13 (MEADOWOPS-DOM-006): off by default so tests/CI/`create_app()`
    # calls that don't explicitly opt in never spin up a background thread.
    scheduler_enabled: bool = False
    scheduler_interval_seconds: int = Field(default=60, gt=0)
    # Unit 17 (MEADOWOPS-DOM-009): steady-state target lag for the
    # Reporting layer (PRD 4.1, S1-FR-9/SR-2) — how many simulation days
    # behind live it should stay caught up to. The "how stale is too
    # stale" threshold is a separate, Analyst-tunable value
    # (exception_rule_threshold.reporting_lag_stale, S1-FR-10), not a
    # Settings field, matching the low_stock/at_risk_po/late_shipment
    # thresholds' own runtime-mutable convention.
    reporting_lag_days: int = Field(default=2, ge=0)
    # Unit 19 (MEADOWOPS-DOM-012, PRD 5.9): the app process itself now opens
    # raw psycopg connections (not through SQLAlchemy's ORM session) as two
    # different Postgres roles - the owner role for the sandbox-refresh job,
    # and meadowops_sandbox for actually running a Playground submission.
    # Only the sandbox role's password is a new setting; the owner role's
    # own credentials are already fully present inside `database_url` and
    # are derived from it below rather than duplicated as separate fields.
    sandbox_role_password: str = Field(min_length=1)
    # PRD 9.2: "a statement timeout ... required, not optional" - a Settings
    # field like scheduler_interval_seconds/reporting_lag_days above, so ops
    # can tune it without a redeploy.
    query_timeout_seconds: float = Field(default=10.0, gt=0)
    # Unit 20 (MEADOWOPS-API-004, DD-2): the shared secret Subsystem 2's
    # internal httpx.AsyncClient (app.core.internal_client) presents as its
    # Bearer credential - same required/no-default/min_length=32 convention
    # as session_secret_key, generated the same way (openssl rand -hex 16).
    # Pre-implementation security review of this unit: a static, non-rotating
    # shared secret is the same posture already accepted for
    # session_secret_key/sandbox_role_password, appropriate here too since
    # DD-2's ASGITransport means this secret never crosses a real network
    # boundary.
    internal_service_token: str = Field(min_length=32)

    def owner_dsn(self) -> str:
        """A plain psycopg-style DSN (not the `postgresql+psycopg://`
        SQLAlchemy URL psycopg.connect() doesn't understand) for the same
        owner role/database `database_url` already points at. Built via
        psycopg's own make_conninfo() (security review, LOW) rather than raw
        f-string interpolation - a password containing a space or a
        backslash would otherwise silently split into extra DSN keywords
        instead of being treated as one value."""
        url = make_url(self.database_url)
        return make_conninfo(
            host=url.host, port=url.port, dbname=url.database,
            user=url.username, password=url.password,
        )

    def sandbox_dsn(self) -> str:
        """Same host/port/database as `database_url`, but as the
        `meadowops_sandbox` role - the one role with no privileges on
        live/reporting/engine, only on `sandbox` (migration 0001)."""
        url = make_url(self.database_url)
        return make_conninfo(
            host=url.host, port=url.port, dbname=url.database,
            user="meadowops_sandbox", password=self.sandbox_role_password,
        )
