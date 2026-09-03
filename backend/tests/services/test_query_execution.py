"""Unit 19 (MEADOWOPS-DOM-012): query execution, tested against the real
`meadowops_sandbox` role and the real dev Postgres instance - the
timeout/cancellation mechanism in particular is meaningless as a mock, so
this follows the project's own convention (test_sandbox_boundary.py,
test_scenario_service.py) of proving DB-level behavior for real rather than
asserting it.
"""

import os
import threading
import time

import psycopg
import pytest

from app.db.base import Base
from app.services.query_execution import (
    QueryConfirmationRequiredError,
    execute_submission,
)
from app.services.sandbox_refresh import refresh_sandbox


@pytest.fixture(scope="module", autouse=True)
def _ensure_registered_and_refreshed(owner_dsn: str):
    import app.db  # noqa: F401 - registers every table on Base.metadata

    refresh_sandbox(owner_dsn, Base.metadata)


def test_plain_read_executes_without_confirmation(sandbox_dsn: str) -> None:
    result = execute_submission(
        sandbox_dsn, "select id, sku from sandbox.product limit 3", confirmed=False
    )
    assert result.status == "success"
    assert result.columns == ["id", "sku"]
    assert result.row_count <= 3
    assert result.truncated is False


def test_write_without_confirmed_raises_confirmation_required(sandbox_dsn: str) -> None:
    with pytest.raises(QueryConfirmationRequiredError) as exc_info:
        execute_submission(sandbox_dsn, "delete from sandbox.product where 1 = 0", confirmed=False)
    assert exc_info.value.classified[0].statement_type.value == "write"


def test_write_without_confirmed_does_not_execute(sandbox_dsn: str) -> None:
    with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("create table if not exists sandbox.exec_probe (id integer primary key)")
        cur.execute("insert into sandbox.exec_probe (id) values (1) on conflict do nothing")
    try:
        with pytest.raises(QueryConfirmationRequiredError):
            execute_submission(
                sandbox_dsn, "delete from sandbox.exec_probe where id = 1", confirmed=False
            )
        with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("select count(*) from sandbox.exec_probe")
            assert cur.fetchone() == (1,)
    finally:
        with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("drop table sandbox.exec_probe")


def test_write_with_confirmed_true_executes(sandbox_dsn: str) -> None:
    with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("create table if not exists sandbox.exec_probe2 (id integer primary key)")
        cur.execute("insert into sandbox.exec_probe2 (id) values (1) on conflict do nothing")
    try:
        result = execute_submission(
            sandbox_dsn, "delete from sandbox.exec_probe2 where id = 1", confirmed=True
        )
        assert result.status == "success"
        with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("select count(*) from sandbox.exec_probe2")
            assert cur.fetchone() == (0,)
    finally:
        with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("drop table sandbox.exec_probe2")


def test_runaway_query_is_cancelled_at_the_app_enforced_timeout(sandbox_dsn: str) -> None:
    result = execute_submission(
        sandbox_dsn, "select pg_sleep(5)", confirmed=False, timeout_seconds=0.5
    )
    assert result.status == "timed_out"
    assert result.duration_ms < 3000
    assert "timeout" in result.error_message.lower()


def test_timeout_is_enforced_even_if_query_tries_to_disable_it(sandbox_dsn: str) -> None:
    """The whole reason this uses out-of-band cancellation, not
    statement_timeout: the sandbox role can freely override its own
    session's GUC (verified empirically before this unit was designed).
    A malicious/careless submission disabling it must not escape the app's
    own enforcement."""
    result = execute_submission(
        sandbox_dsn,
        "set statement_timeout = 0; select pg_sleep(5)",
        confirmed=True,
        timeout_seconds=0.5,
    )
    assert result.status == "timed_out"


def test_malformed_sql_returns_clean_error_not_a_stack_trace(sandbox_dsn: str) -> None:
    result = execute_submission(sandbox_dsn, "select * frooom nowhere", confirmed=False)
    assert result.status == "error"
    assert "Traceback" not in result.error_message
    assert "frooom" in result.error_message


def test_write_against_live_schema_is_rejected_at_the_permission_level(sandbox_dsn: str) -> None:
    result = execute_submission(
        sandbox_dsn, "update live.product set sku = sku", confirmed=True
    )
    assert result.status == "error"
    assert "permission denied" in result.error_message.lower()


def test_large_result_set_is_truncated_to_max_rows(sandbox_dsn: str) -> None:
    result = execute_submission(
        sandbox_dsn,
        "select * from generate_series(1, 1000) as g(n)",
        confirmed=False,
    )
    assert result.status == "success"
    assert result.truncated is True
    assert result.row_count == 500


def test_result_under_limit_is_not_truncated(sandbox_dsn: str) -> None:
    result = execute_submission(
        sandbox_dsn,
        "select * from generate_series(1, 5) as g(n)",
        confirmed=False,
    )
    assert result.status == "success"
    assert result.truncated is False
    assert result.row_count == 5


def test_multi_statement_submission_blocks_a_concurrent_refresh_until_it_finishes(
    sandbox_dsn: str,
) -> None:
    """Security review: without a shared lock held for the submission's
    whole duration, a concurrent refresh's schema-rename could commit
    *between* two statements of this still-open multi-statement submission
    (Postgres's default READ COMMITTED isolation re-resolves unqualified
    names per-statement, not per-transaction) - so a single "consistent"
    submission could silently read two different sandbox generations.
    Proven directly via the real production code path (not a hand-rolled
    connection, unlike this module's other cross-refresh test): a refresh
    started while this multi-statement submission is still mid-flight must
    not complete until the submission itself does."""
    owner_dsn = (
        f"host=localhost port=5434 dbname=meadowops user=meadowops "
        f"password={os.environ['MEADOWOPS_POSTGRES_PASSWORD']}"
    )
    execution_done_at: dict = {}

    def run_submission() -> None:
        execute_submission(
            sandbox_dsn,
            "select pg_sleep(2); select count(*) from product;",
            confirmed=False,
        )
        execution_done_at["t"] = time.monotonic()

    thread = threading.Thread(target=run_submission)
    thread.start()
    time.sleep(0.3)  # let the submission acquire its shared lock first

    refresh_result = refresh_sandbox(owner_dsn, Base.metadata)
    refresh_completed_at = time.monotonic()
    thread.join(timeout=10)

    assert refresh_result.status.value == "complete"
    assert "t" in execution_done_at
    assert refresh_completed_at >= execution_done_at["t"] - 0.05


def test_trapping_exception_handler_is_still_cancelled_cleanly(
    sandbox_dsn: str,
) -> None:
    """Security review raised a specific bypass: a submission wrapping
    itself in a PL/pgSQL exception handler -
        DO $$ BEGIN LOOP BEGIN PERFORM pg_sleep(1000);
        EXCEPTION WHEN OTHERS THEN END; END LOOP; END $$;
    - might swallow conn.cancel()'s ERROR and survive indefinitely. Verified
    directly against this project's own Postgres instance that it does not:
    Postgres documents QUERY_CANCELED (57014) as one of exactly two error
    codes a PL/pgSQL `WHEN OTHERS` handler cannot trap, by design, so an
    admin can always cancel a runaway procedure regardless of its own
    exception handling. This submission is therefore cancelled the same way
    any other timed-out query is - promptly, within the app timeout, not
    requiring the `_escalate_timeout` pg_terminate_backend grace window at
    all - and the backend is actually gone afterward, not just abandoned by
    the app while still running server-side and holding one of
    meadowops_sandbox's 5 connection slots."""
    trapping_sql = (
        "DO $$ BEGIN LOOP BEGIN PERFORM pg_sleep(1000); "
        "EXCEPTION WHEN OTHERS THEN END; END LOOP; END $$;"
    )
    start = time.monotonic()
    result = execute_submission(sandbox_dsn, trapping_sql, confirmed=True, timeout_seconds=0.5)
    elapsed = time.monotonic() - start

    # Cancelled promptly by the app timeout itself - well under the 2s
    # _escalate_timeout grace window, since QUERY_CANCELED isn't trappable.
    assert elapsed < 2.0
    assert result.status == "timed_out"

    # The backend must actually be gone, not just abandoned by the app.
    # Excludes this very check's own backend - its query text contains the
    # literal substring "pg_sleep(1000)" inside the ILIKE pattern below, so
    # without this it would always match itself and the assertion could
    # never fail even if a real leaked backend were also present.
    with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from pg_stat_activity "
            "where usename = 'meadowops_sandbox' and query ilike '%pg_sleep(1000)%' "
            "and pid != pg_backend_pid()"
        )
        (still_running,) = cur.fetchone()
    assert still_running == 0
