import enum
from datetime import datetime
from typing import TypeVar

from sqlalchemy import DateTime, Enum, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

metadata = MetaData(schema="live")

_E = TypeVar("_E", bound=enum.Enum)


def pg_enum(enum_cls: type[_E], name: str) -> Enum:
    """Store each member's lowercase `.value` as the Postgres enum label,
    not its Python member NAME (SQLAlchemy's default) — so raw SQL written
    against `live` (including in the Query Playground, PRD 5.9) sees
    'low'/'erp'/'pending', not 'LOW'/'ERP'/'PENDING'.

    schema="live" is explicit, not inferred from MetaData(schema="live") —
    for hygiene, not reachability: Unit 1 revokes ALL on `live` from
    meadowops_sandbox just as it revokes USAGE on `public`, so the sandbox
    role is equally blocked from a type either way. Keeping these types
    alongside their tables (rather than defaulting to `public`, which Unit 1
    otherwise locks down and expects unused) keeps autogenerate/downgrade
    symmetric. Note for whoever builds the sandbox-refresh job (flagged by
    security review of this unit): only the `meadowops` owner role currently
    has DDL access to these `live`-schema types — no narrower role has been
    granted USAGE on SCHEMA live yet, which that job will need if it can't
    run as owner (see 0001's migration docstring)."""
    return Enum(
        enum_cls,
        name=name,
        schema="live",
        values_callable=lambda cls: [e.value for e in cls],
    )


class Base(DeclarativeBase):
    metadata = metadata


class TimestampMixin:
    """PRD 8.7: all timestamps stored in UTC — timezone-aware columns, not
    naive, so a driver/session-timezone mismatch can't silently store the
    wrong instant."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
