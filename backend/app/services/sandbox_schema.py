"""Unit 36 (MEADOWOPS-DOM-024): describes the tables, columns and
relationships the Analyst can actually query in the Query Playground, so the
UI can show them instead of leaving her to guess table names.

The shape comes from the SQLAlchemy metadata (the only place PKs/FKs live -
the sandbox's own `CREATE TABLE ... AS SELECT` copies carry none), filtered
by the same SANDBOX_MIRRORED_TABLES allowlist the sandbox refresh uses, so
this can never advertise a table the `meadowops_sandbox` role cannot read.
Whether the sandbox currently holds those tables (it is empty until the
first refresh) is a separate runtime fact, read from information_schema.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
from sqlalchemy import MetaData

from app.services.sandbox_refresh import SANDBOX_MIRRORED_TABLES

SANDBOX_SCHEMA = "sandbox"


@dataclass(frozen=True)
class SandboxColumn:
    name: str
    type: str
    nullable: bool
    is_primary_key: bool


@dataclass(frozen=True)
class SandboxTable:
    name: str
    qualified_name: str
    columns: tuple[SandboxColumn, ...]


@dataclass(frozen=True)
class SandboxRelationship:
    from_table: str
    from_column: str
    to_table: str
    to_column: str


@dataclass(frozen=True)
class SandboxSchemaDescription:
    tables: tuple[SandboxTable, ...]
    relationships: tuple[SandboxRelationship, ...]


def describe_sandbox_schema(metadata: MetaData) -> SandboxSchemaDescription:
    mirrored = sorted(
        (t for t in metadata.tables.values() if (t.schema or "live") == "live" and t.name in SANDBOX_MIRRORED_TABLES),
        key=lambda t: t.name,
    )
    names = {t.name for t in mirrored}
    tables = tuple(
        SandboxTable(
            name=t.name,
            qualified_name=f"{SANDBOX_SCHEMA}.{t.name}",
            columns=tuple(
                SandboxColumn(
                    name=c.name,
                    type=str(c.type),
                    nullable=bool(c.nullable),
                    is_primary_key=bool(c.primary_key),
                )
                for c in t.columns
            ),
        )
        for t in mirrored
    )
    relationships = tuple(
        SandboxRelationship(
            from_table=t.name,
            from_column=fk.parent.name,
            to_table=fk.column.table.name,
            to_column=fk.column.name,
        )
        for t in mirrored
        for fk in sorted(t.foreign_keys, key=lambda f: f.parent.name)
        if fk.column.table.name in names
    )
    return SandboxSchemaDescription(tables=tables, relationships=relationships)


def sandbox_has_tables(sandbox_dsn: str) -> bool:
    """True once a refresh has populated the sandbox with at least one
    mirrored table. Read as the restricted sandbox role (what a query will
    actually see, and no DDL-capable owner connection on a plain GET), with a
    short connect timeout. Counts only allowlisted names - the sandbox role
    can CREATE its own tables there, and one of those must not hide the
    "sandbox is empty" hint."""
    with psycopg.connect(sandbox_dsn, connect_timeout=3) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = ANY(%s))",
            (SANDBOX_SCHEMA, sorted(SANDBOX_MIRRORED_TABLES)),
        )
        row = cur.fetchone()
    return bool(row and row[0])
