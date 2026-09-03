"""Unit 19 (MEADOWOPS-DOM-012, PRD 5.9): executes a Query Playground
submission against the `meadowops_sandbox` role, applying an app-enforced
timeout via Postgres's out-of-band cancel protocol - never the session's
own `statement_timeout` GUC. Empirically verified (connecting as
meadowops_sandbox and running `SET statement_timeout = 0` before a
`pg_sleep`) that the role can freely override that setting, confirming
migration 0001's own embedded warning that a GUC-based limit is not a real
enforcement boundary here. `psycopg.Connection.cancel()` instead sends
Postgres's cancel-request protocol message from a second short-lived
connection - unaffected by whatever the target session's own GUCs say,
the same mechanism `psql`'s Ctrl+C uses.

Security review of this unit raised a specific bypass: a submission
wrapping itself in a PL/pgSQL exception handler -
    DO $$ BEGIN LOOP BEGIN PERFORM pg_sleep(1000);
    EXCEPTION WHEN OTHERS THEN END; END LOOP; END $$;
- might swallow cancel()'s ERROR and loop forever. Verified directly
against this project's own Postgres instance (repeatable, not a one-off):
it does not. Postgres documents QUERY_CANCELED (57014) as one of exactly
two error codes (with ASSERT_FAILURE) that a PL/pgSQL `WHEN OTHERS` handler
cannot trap - deliberately, so an admin can always cancel a runaway
procedure regardless of its own exception handling. The trapping
submission above returns via QueryCanceled and the backend disappears from
pg_stat_activity within about a second of the cancel, same as any other
query (see tests/services/test_query_execution.py::
test_trapping_exception_handler_is_still_cancelled_cleanly).

`_escalate_timeout` below still follows the cancel with a
`pg_terminate_backend` after a short grace window - not because PL/pgSQL
trapping defeats cancellation (it doesn't), but as ordinary defense in
depth against any other reason a cancel might not land promptly (a role
can always terminate its own backends without extra grants, empirically
verified). It is expected to be a no-op in the overwhelming majority of
timeouts, cancel already having done the job by the time it would fire.

Every submission also holds a *shared* Postgres advisory lock
(app.domain.query_playground.SANDBOX_ADVISORY_LOCK_KEY) for its whole
duration - app.services.sandbox_refresh holds the same key *exclusively*
for its whole run, so a refresh always waits for every in-flight query to
finish before touching the schema, and a new query always waits for an
in-progress refresh to finish before starting. This is what actually makes
PRD 9.2's "in-flight query completes against a consistent snapshot" hold
for a multi-statement submission, not just a single-statement one - a
refresh's schema-rename mid-transaction would otherwise be visible to a
later statement in the same still-open submission under Postgres's default
READ COMMITTED isolation. The lock is released automatically when this
function's connection closes (session-scoped), on every path - success,
error, cancellation, or forced termination - so there is no separate
unlock call to get wrong.

Row-limiting (PRD 9.2: "row-limited/paginated, not rendered in full") uses
`fetchmany(MAX_RESULT_ROWS + 1)` rather than `fetchall()`, so an
accidentally-huge result set is never fully materialized in app memory
before being truncated.

Multi-statement submissions execute sequentially in one transaction/one
connection; the returned columns/rows reflect the *last* statement that
produced a result set (matches how a SQL scratchpad tool conventionally
shows a multi-statement run's result grid).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import psycopg
from psycopg.rows import dict_row

from app.domain.query_classifier import (
    ClassifiedStatement,
    classify_submission,
    requires_confirmation,
    split_statements,
)
from app.domain.query_playground import (
    MAX_RESULT_ROWS,
    SANDBOX_ADVISORY_LOCK_KEY,
    QuerySubmissionStatus,
    truncate_rows,
)

DEFAULT_TIMEOUT_SECONDS = 10.0
# How long to wait after a cancel() before escalating to
# pg_terminate_backend - long enough that an honest query's normal,
# catchable cancellation isn't raced against a termination it doesn't need.
_TERMINATE_GRACE_SECONDS = 2.0


class QueryConfirmationRequiredError(Exception):
    """A non-read statement was submitted without `confirmed=True`. Callers
    (the API router) catch this and return the classification preview
    without executing or logging anything - nothing has happened yet at
    this point, so there is nothing to log (S1-FR-14 logs executed or
    explicitly-cancelled submissions, not every keystroke-triggered
    preview)."""

    def __init__(self, classified: list[ClassifiedStatement]) -> None:
        self.classified = classified
        super().__init__("confirmation required")


@dataclass(frozen=True)
class QueryExecutionResult:
    status: str  # QuerySubmissionStatus: "success" | "error" | "timed_out"
    columns: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    duration_ms: int = 0
    error_message: str | None = None


def _escalate_timeout(conn: psycopg.Connection, sandbox_dsn: str, backend_pid: int) -> None:
    """Runs on the Timer's own background thread once `timeout_seconds`
    elapses - never blocks the caller. Always escalates to
    pg_terminate_backend after the grace window regardless of whether the
    cancel already worked: terminating an already-finished backend is a
    harmless no-op (pg_terminate_backend on a gone pid just returns/errors
    quietly), and there's no race-free way to check "is it still running"
    from here that would be worth the added complexity."""
    conn.cancel()
    time.sleep(_TERMINATE_GRACE_SECONDS)
    try:
        with psycopg.connect(sandbox_dsn, autocommit=True) as term_conn:
            with term_conn.cursor() as cur:
                cur.execute("SELECT pg_terminate_backend(%s)", (backend_pid,))
    except psycopg.Error:
        pass


def execute_submission(
    sandbox_dsn: str,
    sql: str,
    *,
    confirmed: bool,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> QueryExecutionResult:
    """Raises QueryConfirmationRequiredError if the submission needs
    confirmation and `confirmed` is False - never returns a result in that
    case. Otherwise always returns a QueryExecutionResult (never raises for
    a query-level failure: a syntax error, a permission violation, or a
    timeout are all reported as `status`, per PRD 9.2's "clear, readable
    error shown - never a raw stack trace")."""
    if requires_confirmation(sql) and not confirmed:
        raise QueryConfirmationRequiredError(classify_submission(sql))

    statements = split_statements(sql)
    start = time.monotonic()
    columns: list[str] = []
    rows: list[dict] = []
    row_count = 0
    truncated = False

    try:
        with psycopg.connect(sandbox_dsn, row_factory=dict_row) as conn:
            backend_pid = conn.info.backend_pid
            with conn.cursor() as lock_cur:
                lock_cur.execute(
                    "SELECT pg_advisory_lock_shared(%s)", (SANDBOX_ADVISORY_LOCK_KEY,)
                )
            timer = threading.Timer(
                timeout_seconds, _escalate_timeout, args=(conn, sandbox_dsn, backend_pid)
            )
            timer.start()
            try:
                with conn.cursor() as cur:
                    for statement in statements:
                        cur.execute(statement)
                        if cur.description is not None:
                            columns = [col.name for col in cur.description]
                            fetched = cur.fetchmany(MAX_RESULT_ROWS + 1)
                            rows, truncated = truncate_rows(fetched, MAX_RESULT_ROWS)
                            row_count = len(rows)
                        else:
                            columns = []
                            rows = []
                            row_count = cur.rowcount if cur.rowcount > 0 else 0
                            truncated = False
                conn.commit()
            finally:
                timer.cancel()
    except psycopg.errors.QueryCanceled:
        return QueryExecutionResult(
            status=QuerySubmissionStatus.TIMED_OUT.value,
            duration_ms=int((time.monotonic() - start) * 1000),
            error_message=(
                f"Query exceeded the {timeout_seconds:.0f}s statement timeout "
                "and was cancelled."
            ),
        )
    except psycopg.Error as exc:
        return QueryExecutionResult(
            status=QuerySubmissionStatus.ERROR.value,
            duration_ms=int((time.monotonic() - start) * 1000),
            error_message=str(exc).strip(),
        )

    return QueryExecutionResult(
        status=QuerySubmissionStatus.SUCCESS.value,
        columns=columns,
        rows=rows,
        row_count=row_count,
        truncated=truncated,
        duration_ms=int((time.monotonic() - start) * 1000),
    )
