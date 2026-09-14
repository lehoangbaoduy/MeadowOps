from app.db.base import Base, metadata
from app.db import (  # noqa: F401 -- registers tables on Base.metadata
    auth,
    chat,
    dimensions,
    evaluation,
    exception_flags,
    exception_rules,
    facts,
    human_review,
    kpi,
    ledger,
    portfolio,
    query_log,
    reporting,
    scenario,
    scheduling,
    world_state,
)

__all__ = ["Base", "metadata"]
