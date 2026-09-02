from app.db.base import Base, metadata
from app.db import dimensions, facts, ledger, world_state  # noqa: F401 -- registers tables on Base.metadata

__all__ = ["Base", "metadata"]
