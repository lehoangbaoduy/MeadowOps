from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import boto3
from botocore.config import Config as BotoConfig
from fastapi import Depends, FastAPI

from app.api.admin_query_log import router as admin_query_log_router
from app.api.admin_scenarios import router as admin_scenarios_router
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.customers import router as customers_router
from app.api.dashboard import router as dashboard_router
from app.api.evaluation import router as evaluation_router
from app.api.ledger import router as ledger_router
from app.api.master_data import router as master_data_router
from app.api.portfolio import router as portfolio_router
from app.api.query_playground import router as query_playground_router
from app.core.auth import require_authenticated
from app.core.body_size_limit import (
    MULTIPART_OVERHEAD_BYTES,
    MaxBodySizeMiddleware,
    RequestBodyTooLargeError,
    request_body_too_large_handler,
)
from app.core.chat_registry import ChatConnectionRegistry
from app.core.config import Settings
from app.core.internal_client import build_subsystem2_client
from app.core.rate_limit import LoginRateLimiter
from app.core.ws_tickets import WsTicketStore
from app.db.session import make_engine
from app.domain.scheduler import build_scheduler

# Unit 21a (MEADOWOPS-DOM-014, PRD 6.13): the WS ticket handshake window,
# not the session's own lifetime — kept short and fixed rather than a
# Settings field, mirroring how short-lived this credential is meant to be
# (see app.core.ws_tickets' own docstring).
_CHAT_WS_TICKET_TTL_SECONDS = 20


def create_app(settings: Settings | None = None) -> FastAPI:
    """App factory, not a module-level `app = FastAPI()` — settings and
    later per-unit routers (admin CRUD, Query Playground, Subsystem 2) are
    injected here rather than imported as globals, keeping the app
    constructible with test-specific settings."""
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        # Engine created once per app instance (Unit 8, DD-11) — not a
        # module-level global, so each `create_app()` in tests gets its own
        # pool — and disposed on shutdown rather than left to the GC.
        # `create_engine` itself is lazy (no connection opens here), so
        # routes that never touch the DB (e.g. /health) are unaffected by
        # this even when lifespan doesn't run (a bare `TestClient(app)` used
        # without `with` skips startup/shutdown entirely).
        app.state.engine = make_engine(settings.database_url)
        # Unit 20 (MEADOWOPS-API-004, DD-2): built against this same running
        # `app` instance, not a second create_app() - see
        # app.core.internal_client's own docstring for why.
        app.state.subsystem2_client = build_subsystem2_client(
            app, service_token=settings.internal_service_token
        )
        # Unit 32 (MEADOWOPS-INFRA-005): built once here, not per-request
        # like LocalFilesystemAttachmentStorage - a boto3 client holds real
        # connection-pooling state worth keeping (app.core.storage's
        # get_attachment_storage reads it back off app.state, never
        # constructs its own). None when the backend is "local" (the
        # default) - Settings' own validator guarantees the four r2_*
        # fields are all present whenever attachment_storage_backend == "r2",
        # so no further None-checking is needed past this point. Explicit
        # connect/read timeouts + bounded retries (pre-implementation
        # security review, decision 1627): without them, a slow or hanging
        # R2 connection could hold a threadpool slot shared with every other
        # sync route in this app (get_message_attachment_route included)
        # indefinitely - a local disk read can't produce that failure mode.
        app.state.r2_client = None
        if settings.attachment_storage_backend == "r2":
            assert settings.r2_access_key_id is not None
            assert settings.r2_secret_access_key is not None
            app.state.r2_client = boto3.client(
                "s3",
                endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
                aws_access_key_id=settings.r2_access_key_id.get_secret_value(),
                aws_secret_access_key=settings.r2_secret_access_key.get_secret_value(),
                region_name="auto",
                config=BotoConfig(
                    connect_timeout=5,
                    read_timeout=10,
                    retries={"max_attempts": 3, "mode": "standard"},
                ),
            )
        # Unit 13: opt-in background scheduler (settings.scheduler_enabled,
        # default False) — off for tests/CI, and for any create_app() call
        # that doesn't explicitly ask for it, so no test unexpectedly gets
        # a background thread advancing the shared dev database's clock.
        scheduler = None
        if settings.scheduler_enabled:
            scheduler = build_scheduler(
                app.state.engine,
                interval_seconds=settings.scheduler_interval_seconds,
                reporting_lag_days=settings.reporting_lag_days,
                stale_decision_after_days=settings.stale_decision_after_days,
                chat_deadline_approaching_within_hours=settings.chat_deadline_approaching_within_hours,
            )
            scheduler.start()
        yield
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        await app.state.subsystem2_client.aclose()
        if app.state.r2_client is not None:
            app.state.r2_client.close()
        app.state.engine.dispose()

    # docs/redoc/openapi disabled: unauthenticated by default, an
    # unnecessary information-disclosure surface for a two-person internal
    # tool (PRD 5.1) — security review of this unit.
    app = FastAPI(
        title="MeadowOps API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    # Unit 30c (MEADOWOPS-UI-005, security review): a global cap ahead of
    # routing/form-parsing entirely - see app.core.body_size_limit's own
    # module docstring for why the attachment upload route's own read-bound
    # can't do this alone. Sized off max_attachment_size_bytes (the largest
    # legitimate request body on this API) plus a fixed multipart-encoding
    # margin; every other route's JSON bodies are far smaller, so this costs
    # them nothing.
    app.add_middleware(
        MaxBodySizeMiddleware,
        max_bytes=settings.max_attachment_size_bytes + MULTIPART_OVERHEAD_BYTES,
    )
    app.add_exception_handler(RequestBodyTooLargeError, request_body_too_large_handler)
    # Unit 17a (MEADOWOPS-DOM-010): one instance per app, not a module-level
    # global, so tests constructing independent create_app() calls don't
    # share rate-limit state with each other.
    app.state.login_rate_limiter = LoginRateLimiter(
        max_attempts=settings.login_rate_limit_max_attempts,
        window_seconds=settings.login_rate_limit_window_seconds,
    )
    # Unit 21a: one instance per app (never a module-level global), same
    # reasoning as login_rate_limiter above — independent create_app()
    # calls in tests must not share ticket/connection state.
    app.state.chat_ws_tickets = WsTicketStore(ttl_seconds=_CHAT_WS_TICKET_TTL_SECONDS)
    app.state.chat_connections = ChatConnectionRegistry()
    # Unit 22 (MEADOWOPS-DOM-016): no real Anthropic SDK adapter exists yet
    # (Phase 4, blocker B3 - no API key configured). app.api.admin_scenarios.
    # regenerate_scenario_route returns a clean 503 while this is None;
    # tests substitute a MockClaudeClient via app.state.claude_client.
    app.state.claude_client = None
    app.include_router(auth_router)
    app.include_router(master_data_router)
    app.include_router(customers_router)
    app.include_router(dashboard_router)
    app.include_router(admin_scenarios_router)
    app.include_router(query_playground_router)
    app.include_router(chat_router)
    app.include_router(ledger_router)
    app.include_router(evaluation_router)
    app.include_router(portfolio_router)
    app.include_router(admin_query_log_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/me")
    def me(identity: dict[str, str] = Depends(require_authenticated)) -> dict[str, str]:
        return identity

    return app
