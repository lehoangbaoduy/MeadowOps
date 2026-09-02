"""DB session wiring for the FastAPI app itself (Unit 8, DD-11). Everything
upstream of the running app (migrations, the baseline seeder, test fixtures
outside this dependency) keeps constructing its own short-lived engine
directly from `os.environ["MEADOWOPS_DATABASE_URL"]` — this module is only
for request-scoped sessions handed out via `Depends(get_session)`.
"""

from collections.abc import Generator

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


def make_engine(database_url: str) -> Engine:
    return create_engine(database_url)


def get_session(request: Request) -> Generator[Session, None, None]:
    """`request.app.state.engine` is created once in the app's lifespan
    (see main.py) and disposed on shutdown — not per-request, and not a
    module-level global, so tests constructing their own `create_app()`
    each get an independent engine/pool."""
    with Session(request.app.state.engine) as session:
        yield session
