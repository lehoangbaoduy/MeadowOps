from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from app.api.customers import router as customers_router
from app.api.master_data import router as master_data_router
from app.core.auth import require_builder
from app.core.config import Settings
from app.db.session import make_engine


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
        yield
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
    app.include_router(master_data_router)
    app.include_router(customers_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/me")
    def me(identity: dict[str, str] = Depends(require_builder)) -> dict[str, str]:
        return identity

    return app
