"""Unit 19 (MEADOWOPS-DOM-012, PRD 5.9): sandbox refresh — copies `live`
schema tables (Subsystem 1 operational + Decision & Event Ledger, PRD 4.1)
into the meadowops_sandbox role's own `sandbox` schema via a
staging-schema-then-atomic-rename swap. Never a `DROP SCHEMA sandbox
CASCADE` while a Playground query might be mid-flight - PRD 9.2's Query
Playground edge case row: "Sandbox refresh triggered mid-query -> the
in-flight query completes against a consistent snapshot or fails cleanly -
never a silently corrupted read."

The whole run holds app.domain.query_playground.SANDBOX_ADVISORY_LOCK_KEY
*exclusively* (app.services.query_execution holds the same key *shared*,
for one submission's whole duration) - a refresh therefore always waits for
every in-flight Playground query to finish before it does anything, and any
new query always waits for an in-progress refresh to finish before it
starts. Security review of this unit: this is what actually closes the gap
a plain schema-rename doesn't - under Postgres's default READ COMMITTED
isolation, a later statement in an *already-open* multi-statement
submission would otherwise see the swap's committed DDL mid-submission,
reading two different data generations in one "single" query. It also
subsumes two narrower problems the advisory lock makes structurally
impossible via this code path: app.api.query_playground no longer needs
its own in-process threading.Lock (this serializes correctly across worker
processes too, since advisory locks are database-session-scoped, not
per-process), and a refresh's own post-swap cleanup can no longer find a
reader still holding a lock on the old data, because no reader can still be
running by the time a refresh gets past its own lock acquisition.

Runs entirely as the `meadowops` owner role — the only role with DDL on
these schemas (app.db.base.pg_enum's own docstring) — with an explicit,
non-ambient search_path (never `sandbox`/`sandbox_staging`) and fully-
qualified names throughout, per migration 0001's own embedded warning: the
meadowops_sandbox role holds CREATE on `sandbox` today (and is granted
CREATE on `sandbox_staging` only in the final step before swap, right
before it becomes the schema named `sandbox`), so an owner-role process
that let an unqualified name resolve into a schema meadowops_sandbox can
write to would be the classic CVE-2018-1058 search_path privilege-
escalation shape this migration already flagged for whoever built this job.
(Empirically confirmed as a non-issue in practice too: meadowops_sandbox
has no database-level CREATE privilege, so it cannot pre-plant a
same-named schema ahead of this job even without the search_path
precaution - the precaution is defense in depth, not the only barrier.)

Table/schema names interpolated into SQL below come only from the
`SANDBOX_MIRRORED_TABLES` allowlist and hardcoded schema-name constants,
never from user input — the Query Playground's own arbitrary user SQL
never reaches this module at all, only app.services.query_execution does.

`SANDBOX_MIRRORED_TABLES` is an explicit allowlist, not a denylist of
excluded tables (security review of this unit): migration 0001 designed
the live/reporting/engine boundary as deny-by-default specifically so
nobody has to remember to lock down a new table - a denylist here would
invert that, silently mirroring any future `live` table (a credential, a
webhook secret, PII) into a schema every authenticated user's own arbitrary
SQL can read, with no review gate. A new `live` table therefore is *not*
mirrored until someone deliberately adds it here. Two tables are
deliberately never mirrored regardless: `user` (password_hash - copying
credential material into the sandbox would hand any Analyst a hash to
attack offline) and `query_log` (the Playground's own audit trail -
mirroring it into the sandbox it's auditing is circular and adds nothing
for open-ended SQL practice).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg
from sqlalchemy import MetaData

from app.domain.query_playground import SANDBOX_ADVISORY_LOCK_KEY, SandboxRefreshStatus

STAGING_SCHEMA = "sandbox_staging"
LIVE_SANDBOX_SCHEMA = "sandbox"
OLD_SCHEMA = "sandbox_old"

# Explicit allowlist (see module docstring for why this isn't a denylist).
# Update this set deliberately whenever a new `live` table should be
# practice-queryable - never assume a new table belongs here by default.
SANDBOX_MIRRORED_TABLES = frozenset(
    {
        "carrier",
        "customer",
        "date_dim",
        "days_of_supply_snapshot",
        "decision_event",
        "exception_flag",
        "exception_rule_threshold",
        "inventory_snapshot",
        "inventory_transaction",
        "kpi_snapshot",
        "product",
        "purchase_order",
        "purchase_order_lifecycle_event",
        "purchase_order_line",
        "sales_order",
        "sales_order_lifecycle_event",
        "sales_order_line",
        "scheduled_tick",
        "shipment",
        "simulation_clock",
        "supplier",
        "warehouse",
        "warehouse_transfer",
        "world_state",
    }
)

# Pinned to exclude both sandbox schemas, reissued at the start of every
# step below (each step owns and closes its own transaction, so a step that
# rolls back also reverts this session-level SET - reissuing is cheap and
# removes any need to track that by hand).
_PIN_SEARCH_PATH_SQL = "SET search_path = pg_catalog"


@dataclass(frozen=True)
class SandboxRefreshResult:
    id: uuid.UUID
    status: SandboxRefreshStatus
    tables_mirrored: int
    started_at: datetime
    completed_at: datetime
    error: str | None = None


def _live_table_names(metadata: MetaData) -> list[str]:
    """`live`-schema tables whose name is also in the allowlist. Both
    conditions matter: the schema check alone would mirror any new `live`
    table by default (the denylist problem this allowlist exists to avoid);
    the allowlist check alone would also match a same-named table in
    another schema - e.g. `reporting.inventory_snapshot` shares its name
    with `live.inventory_snapshot` (Unit 17's lagged shadow-copy pattern),
    and without the schema check both would be selected, causing
    `_rebuild_staging` to attempt `CREATE TABLE ... "inventory_snapshot"`
    twice and fail with "relation already exists" - caught by actually
    running this against the real dev database, not just reading the code."""
    return sorted(
        t.name
        for t in metadata.tables.values()
        if (t.schema or "live") == "live" and t.name in SANDBOX_MIRRORED_TABLES
    )


def _cleanup_stale_old_schema(conn: psycopg.Connection) -> None:
    """Best-effort: clears a previous cycle's leftover `sandbox_old` (e.g.
    left behind by a manual psql session outside this app, since the
    advisory lock above only protects this module's own code path). Never
    fatal - this cycle's swap doesn't depend on it."""
    with conn.cursor() as cur:
        cur.execute(_PIN_SEARCH_PATH_SQL)
        cur.execute("SET LOCAL lock_timeout = '2s'")
        try:
            cur.execute(f"DROP SCHEMA IF EXISTS {OLD_SCHEMA} CASCADE")
        except psycopg.errors.LockNotAvailable:
            conn.rollback()
            return
    conn.commit()


def _rebuild_staging(conn: psycopg.Connection, table_names: list[str]) -> None:
    with conn.cursor() as cur:
        cur.execute(_PIN_SEARCH_PATH_SQL)
        cur.execute(f"DROP SCHEMA IF EXISTS {STAGING_SCHEMA} CASCADE")
        cur.execute(f"CREATE SCHEMA {STAGING_SCHEMA}")
        for name in table_names:
            cur.execute(
                f'CREATE TABLE {STAGING_SCHEMA}."{name}" AS SELECT * FROM live."{name}"'
            )
    conn.commit()


def _swap_schemas(conn: psycopg.Connection, table_names: list[str]) -> None:
    with conn.cursor() as cur:
        cur.execute(_PIN_SEARCH_PATH_SQL)
        # Grants applied to sandbox_staging now carry over by schema OID
        # when it's renamed below - Postgres grants follow the object, not
        # its name (app.db.base.pg_enum's docstring makes the same point
        # about types). Granted only at this last moment, not while the
        # copy above was in progress, to keep the window where
        # meadowops_sandbox holds CREATE on this not-yet-public schema as
        # short as possible.
        if table_names:
            cur.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
                f"IN SCHEMA {STAGING_SCHEMA} TO meadowops_sandbox"
            )
        # FOR ROLE CURRENT_USER, not a hardcoded "meadowops" — this function
        # always runs as owner_dsn's role, whatever it's named in a given
        # environment (see alembic/versions/0001_create_schemas_and_sandbox
        # _role.py's matching fix for the full rationale).
        cur.execute(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE CURRENT_USER IN SCHEMA {STAGING_SCHEMA} "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO meadowops_sandbox"
        )
        cur.execute(f"GRANT USAGE, CREATE ON SCHEMA {STAGING_SCHEMA} TO meadowops_sandbox")

        # The atomic step: two catalog-only renames in one transaction. A
        # session already mid-query against the old `sandbox`-named tables
        # keeps its already-resolved OIDs regardless of what these renames
        # do to pg_namespace - it is unaffected either way. (No such
        # session can exist here anyway - the exclusive advisory lock this
        # module's caller holds guarantees zero in-flight queries at this
        # point.)
        cur.execute(f"ALTER SCHEMA {LIVE_SANDBOX_SCHEMA} RENAME TO {OLD_SCHEMA}")
        cur.execute(f"ALTER SCHEMA {STAGING_SCHEMA} RENAME TO {LIVE_SANDBOX_SCHEMA}")
    conn.commit()


def _cleanup_old_schema(conn: psycopg.Connection) -> None:
    """Deliberately its own transaction, run only after the swap above has
    already committed - a failure or lock timeout here must never roll back
    the swap. The exclusive advisory lock this module's caller holds
    guarantees no Playground query is reading the just-renamed-away tables
    at this point, so in practice this DROP never has to wait on one; the
    lock_timeout is defense in depth against some other, non-Playground
    holder (e.g. a manual psql session)."""
    with conn.cursor() as cur:
        cur.execute(_PIN_SEARCH_PATH_SQL)
        cur.execute("SET LOCAL lock_timeout = '5s'")
        try:
            cur.execute(f"DROP SCHEMA IF EXISTS {OLD_SCHEMA} CASCADE")
        except psycopg.errors.LockNotAvailable:
            conn.rollback()
            return
    conn.commit()


def refresh_sandbox(owner_dsn: str, metadata: MetaData) -> SandboxRefreshResult:
    """Runs the full refresh synchronously on the caller's thread - a
    nightly/on-demand job, never a hot request path, so no async/background
    task machinery is needed here. The caller decides when this runs (an
    authenticated "Refresh sandbox" route, or a future scheduled job -
    neither is wired up by this function itself, matching
    app.domain.scheduler's own separation between the mechanism and what
    triggers it).

    Holds SANDBOX_ADVISORY_LOCK_KEY exclusively for the entire call (see
    module docstring) - acquired as the very first statement on this
    connection, so it also naturally serializes two refreshes racing each
    other (the second simply waits its turn and then runs against an
    already-fresh mirror, rather than erroring)."""
    refresh_id = uuid.uuid4()
    started_at = datetime.now(UTC)
    table_names = _live_table_names(metadata)

    try:
        with psycopg.connect(owner_dsn) as conn:
            with conn.cursor() as lock_cur:
                lock_cur.execute(_PIN_SEARCH_PATH_SQL)
                lock_cur.execute(
                    "SELECT pg_advisory_lock(%s)", (SANDBOX_ADVISORY_LOCK_KEY,)
                )
            conn.commit()

            _cleanup_stale_old_schema(conn)
            _rebuild_staging(conn, table_names)
            _swap_schemas(conn, table_names)
            _cleanup_old_schema(conn)
    except Exception as exc:  # noqa: BLE001 - reported via the result, not raised
        return SandboxRefreshResult(
            id=refresh_id,
            status=SandboxRefreshStatus.FAILED,
            tables_mirrored=0,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            error=str(exc),
        )

    return SandboxRefreshResult(
        id=refresh_id,
        status=SandboxRefreshStatus.COMPLETE,
        tables_mirrored=len(table_names),
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )
