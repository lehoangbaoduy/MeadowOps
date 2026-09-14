from pathlib import Path
from typing import Literal

from psycopg.conninfo import make_conninfo
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from app.domain.attachment_validation import DEFAULT_MAX_ATTACHMENT_SIZE_BYTES


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
    # Unit 24 (MEADOWOPS-DOM-018, PRD 4.4): "flagged after a configurable
    # period rather than sitting in limbo indefinitely" - no PRD-specified
    # number, so this is a Settings field like reporting_lag_days above
    # rather than a hardcoded constant. 30 is a monthly-review-cadence
    # default, not a PRD requirement - ops can tune it without a redeploy.
    # ge=1, not ge=0 (security review, LOW): 0 would mass-flag every open
    # decision as STALE on the very next scheduler tick - a misconfigured
    # "no delay" is never a meaningful staleness threshold.
    stale_decision_after_days: int = Field(default=30, ge=1)
    # Unit 30a (MEADOWOPS-UI-003, PRD 6.1): "Response windows: default 3-5
    # real-world days per round" - the PRD gives a range, not one number;
    # 4 is the midpoint, tunable without a redeploy like the Settings
    # fields above it. app.services.chat.send_message reads this via an
    # explicit function argument, not by importing Settings itself
    # (app.api.chat passes it through), same convention as
    # reporting_lag_days/stale_decision_after_days.
    chat_response_window_days: int = Field(default=4, ge=1)
    # How far ahead of deadline_at the scheduler's deadline sweep
    # (app.services.notifications.sweep_thread_deadlines) starts treating a
    # still-open thread as "approaching" rather than merely "open" - hours,
    # not days, since a multi-day response window makes a same-day warning
    # more useful than a whole extra day's notice.
    chat_deadline_approaching_within_hours: int = Field(default=24, ge=1)
    # Unit 30c (MEADOWOPS-UI-005, PRD 380): "stored in object storage,
    # never in the operational Postgres database." Filesystem-backed for
    # now (app.core.storage's own docstring: Phase 4 owns real deployment,
    # not yet decided between Railway/Render/Fly - PRD 8.2). Defaults to a
    # directory under the backend package itself so it resolves the same
    # way regardless of the invoking process's own cwd (mirrors
    # app.domain.kpi_sql's _SQL_DIR pattern) - not committed to source
    # control (see repo-root .gitignore).
    attachment_storage_dir: str = Field(
        default_factory=lambda: str(
            Path(__file__).resolve().parents[2] / "var" / "chat_attachments"
        )
    )
    # PRD 380: "a hard per-file size cap" - no PRD-specified number, chosen
    # as a sane default for the images/PDF/CSV allowlist at this project's
    # scale, tunable without a redeploy like the Settings fields above it.
    max_attachment_size_bytes: int = Field(
        default=DEFAULT_MAX_ATTACHMENT_SIZE_BYTES, gt=0
    )
    # Unit 32 (MEADOWOPS-INFRA-005): object storage backend for
    # app.core.storage. "local" (default) is LocalFilesystemAttachmentStorage
    # - every existing test/CI/Docker Compose flow keeps working with zero
    # new required config. "r2" swaps in R2AttachmentStorage against
    # Cloudflare R2 (S3-compatible), chosen so attachment bytes survive a
    # Railway redeploy - the container-local filesystem doesn't (found
    # during B1/B2, Phase 3). The four r2_* fields are Optional at the type
    # level only so a "local" deployment never has to set them; the
    # model_validator below enforces the real invariant (r2_* present iff
    # backend == "r2") at Settings() construction, matching this class's
    # existing fail-fast-at-startup convention for every other required
    # secret (session_secret_key, database_url, sandbox_role_password,
    # internal_service_token) rather than a per-request runtime check that
    # could let a misconfigured "r2" backend silently construct a broken
    # client, or a forgotten backend flag silently keep writing to ephemeral
    # local disk with no error signal - both flagged at this unit's
    # pre-implementation security review (decision 1627).
    attachment_storage_backend: Literal["local", "r2"] = "local"
    r2_account_id: str | None = None
    # SecretStr, unlike sandbox_role_password/internal_service_token above -
    # security review of this unit: those two are an accepted existing
    # pattern, not retrofitted here, but a new field is a fresh choice, and
    # SecretStr closes the narrow residual risk of an accidental
    # repr(settings)/str(settings) landing in a log line. Call
    # .get_secret_value() only at the single boto3-client-construction site
    # (app.main's lifespan).
    r2_access_key_id: SecretStr | None = None
    r2_secret_access_key: SecretStr | None = None
    r2_bucket_name: str | None = None
    # Phase 4 blocker B3: the real Anthropic SDK adapter
    # (app.domain.claude_client_anthropic.AnthropicClaudeClient). Bare
    # ANTHROPIC_API_KEY, not MEADOWOPS_-prefixed — an explicit
    # validation_alias bypasses env_prefix for this one field, matching the
    # name every other tool in this repo (e2e fixtures, .env.example) already
    # uses. claude_client_enabled stays MEADOWOPS_-prefixed and defaults to
    # False, same off-by-default convention as scheduler_enabled ("tests/CI/
    # `create_app()` calls that don't explicitly opt in never spin up a
    # background thread") - required here for the same reason plus a sharper
    # one: tests/conftest.py's load_dotenv() puts a real repo-root
    # ANTHROPIC_API_KEY into every test process's environment, so "key
    # present" alone can't be the live-vs-mock switch without every one of
    # the 1288 backend tests either constructing a real client at
    # create_app() or making live billed API calls the moment a route under
    # test forgets to substitute app.state.claude_client with a
    # MockClaudeClient. The validator below enforces enabled implies key
    # present; the reverse (key present but not enabled) is the expected
    # default local-dev/CI/test shape, not an error.
    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias="ANTHROPIC_API_KEY"
    )
    claude_client_enabled: bool = False
    claude_client_timeout_seconds: float = Field(default=60.0, gt=0)

    @model_validator(mode="after")
    def _validate_claude_client_enabled(self) -> "Settings":
        # Not just `is None`: found empirically (2026-09-14) while building
        # this adapter - the repo-root .env's own ANTHROPIC_API_KEY line was
        # present but blank (`ANTHROPIC_API_KEY=`, no value), which
        # pydantic-settings treats as SecretStr("") rather than None. An
        # `is None` check alone would let claude_client_enabled=True pass
        # validation with a blank key, deferring the failure to a cryptic
        # SDK-internal TypeError ("Could not resolve authentication method")
        # at the first real API call instead of at startup.
        key = self.anthropic_api_key
        if self.claude_client_enabled and (key is None or not key.get_secret_value().strip()):
            raise ValueError(
                "claude_client_enabled=True requires a non-empty ANTHROPIC_API_KEY"
            )
        return self

    @model_validator(mode="after")
    def _validate_attachment_storage_backend(self) -> "Settings":
        r2_fields = {
            "r2_account_id": self.r2_account_id,
            "r2_access_key_id": self.r2_access_key_id,
            "r2_secret_access_key": self.r2_secret_access_key,
            "r2_bucket_name": self.r2_bucket_name,
        }
        missing = sorted(name for name, value in r2_fields.items() if value is None)
        present = sorted(name for name, value in r2_fields.items() if value is not None)
        # Error messages name only field names, never the Settings object
        # itself or any field value (security review, this unit) - printing
        # `self`/`vars(self)` here would put secret values into a startup
        # crash log.
        if self.attachment_storage_backend == "r2" and missing:
            raise ValueError(
                "attachment_storage_backend='r2' requires all of: "
                + ", ".join(missing)
            )
        if self.attachment_storage_backend == "local" and present:
            raise ValueError(
                "attachment_storage_backend='local' but these r2_* fields "
                "are set: " + ", ".join(present) + " (set "
                "attachment_storage_backend='r2' too, or unset them)"
            )
        return self

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
