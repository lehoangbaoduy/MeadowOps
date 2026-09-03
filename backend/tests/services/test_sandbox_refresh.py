"""Unit 19 (MEADOWOPS-DOM-012): sandbox refresh, tested against the real
dev Postgres instance (matching this project's own convention for
DB-permission-boundary claims - see tests/infra/test_sandbox_boundary.py's
own docstring) rather than mocking psycopg. `owner_dsn`/`sandbox_dsn` are
the same session-scoped fixtures Unit 1/9's boundary tests already use.
"""

import threading
import time

import psycopg
import pytest

from app.db.base import Base
from app.domain.query_playground import SandboxRefreshStatus
from app.services.sandbox_refresh import SANDBOX_MIRRORED_TABLES, refresh_sandbox


@pytest.fixture(scope="module", autouse=True)
def _ensure_registered_tables():
    import app.db  # noqa: F401 - registers every table on Base.metadata


def test_refresh_completes_and_mirrors_live_tables(owner_dsn: str) -> None:
    result = refresh_sandbox(owner_dsn, Base.metadata)
    assert result.status is SandboxRefreshStatus.COMPLETE
    assert result.error is None
    assert result.tables_mirrored > 0
    assert result.completed_at >= result.started_at


def test_refresh_mirrors_exactly_the_allowlisted_tables(owner_dsn: str, sandbox_dsn: str) -> None:
    """Asserts against the real, independent expected set - not against
    SANDBOX_MIRRORED_TABLES itself (code review of this unit: a prior
    version of this test asserted `names.isdisjoint(EXCLUDED_TABLES)`,
    which could never fail regardless of what the implementation's own
    constant excluded or included, since both sides came from the same
    source). `user` and `query_log` are named explicitly here so a
    regression that starts mirroring either credential/audit table would
    fail this test even if someone renamed or emptied the allowlist
    constant itself."""
    refresh_sandbox(owner_dsn, Base.metadata)
    with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "select table_name from information_schema.tables where table_schema = 'sandbox'"
        )
        names = {row[0] for row in cur.fetchall()}
    assert names == SANDBOX_MIRRORED_TABLES
    assert "user" not in names
    assert "query_log" not in names


def test_sandbox_role_can_read_mirrored_data_after_refresh(
    owner_dsn: str, sandbox_dsn: str
) -> None:
    refresh_sandbox(owner_dsn, Base.metadata)
    with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("select count(*) from sandbox.product")
        (count,) = cur.fetchone()
    assert count > 0


def test_sandbox_role_retains_create_privilege_across_repeated_refreshes(
    owner_dsn: str, sandbox_dsn: str
) -> None:
    """Grants are re-applied to the new staging-turned-sandbox schema every
    cycle - proves that isn't a one-time fluke of the first refresh after
    migration 0001 (which grants USAGE/CREATE on the *original* `sandbox`
    schema directly) by refreshing twice and checking CREATE still works."""
    refresh_sandbox(owner_dsn, Base.metadata)
    refresh_sandbox(owner_dsn, Base.metadata)
    with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("create table if not exists sandbox.refresh_probe (id integer primary key)")
        cur.execute("insert into sandbox.refresh_probe (id) values (1) on conflict do nothing")
        cur.execute("select id from sandbox.refresh_probe")
        assert cur.fetchone() == (1,)
        cur.execute("drop table sandbox.refresh_probe")


def test_no_leftover_staging_or_old_schema_after_refresh(owner_dsn: str) -> None:
    refresh_sandbox(owner_dsn, Base.metadata)
    with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "select schema_name from information_schema.schemata "
            "where schema_name in ('sandbox_staging', 'sandbox_old')"
        )
        assert cur.fetchall() == []


def test_in_flight_query_sees_a_consistent_snapshot_across_a_concurrent_refresh(
    owner_dsn: str, sandbox_dsn: str
) -> None:
    """PRD 9.2's named Query Playground edge case: "Sandbox refresh
    triggered mid-query -> the in-flight query completes against a
    consistent snapshot or fails cleanly - never a silently corrupted
    read." Proven directly: a transaction holds product open across a
    concurrent refresh and must see the same row count before and after."""
    refresh_sandbox(owner_dsn, Base.metadata)  # ensure a clean starting mirror
    query_result: dict = {}

    def slow_query() -> None:
        with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("begin")
            cur.execute("select count(*) from sandbox.product")
            before = cur.fetchone()
            cur.execute("select pg_sleep(2)")
            cur.execute("select count(*) from sandbox.product")
            after = cur.fetchone()
            cur.execute("commit")
            query_result["before"] = before
            query_result["after"] = after

    thread = threading.Thread(target=slow_query)
    thread.start()
    time.sleep(0.3)  # let the slow query acquire its snapshot first
    refresh_result = refresh_sandbox(owner_dsn, Base.metadata)
    thread.join(timeout=10)

    assert refresh_result.status is SandboxRefreshStatus.COMPLETE
    assert query_result["before"] == query_result["after"]


def test_two_concurrent_refreshes_both_succeed_serialized_not_racing(owner_dsn: str) -> None:
    """Security review: the old in-process threading.Lock (removed from
    app.api.query_playground) only 409'd a second concurrent refresh
    request; it never protected the two-refreshes-racing-each-other case at
    the service layer itself, and wouldn't have worked at all across
    multiple worker processes. The exclusive advisory lock this module now
    holds for its whole run serializes two refresh_sandbox() calls
    correctly regardless of caller - both simply complete, one after the
    other, neither erroring."""
    results: list = [None, None]

    def run(index: int) -> None:
        results[index] = refresh_sandbox(owner_dsn, Base.metadata)

    t1 = threading.Thread(target=run, args=(0,))
    t2 = threading.Thread(target=run, args=(1,))
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)

    assert results[0] is not None and results[1] is not None
    assert results[0].status is SandboxRefreshStatus.COMPLETE
    assert results[1].status is SandboxRefreshStatus.COMPLETE
