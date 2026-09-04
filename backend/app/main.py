from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from app.api.admin_scenarios import router as admin_scenarios_router
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.customers import router as customers_router
from app.api.dashboard import router as dashboard_router
from app.api.master_data import router as master_data_router
from app.api.query_playground import router as query_playground_router
from app.core.auth import require_authenticated
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
            )
            scheduler.start()
        yield
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        await app.state.subsystem2_client.aclose()
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

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/me")
    def me(identity: dict[str, str] = Depends(require_authenticated)) -> dict[str, str]:
        return identity

    return app
