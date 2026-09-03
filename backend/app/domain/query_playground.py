"""Unit 19 (MEADOWOPS-DOMAIN-010, spec MEADOWOPS-DOM-012, PRD 5.9/S1-FR-13/14):
pure domain logic for the Query Playground's two lifecycles — a single
submission's own status, and a sandbox-refresh run's own status. Execution,
persistence, and the sandbox-refresh job itself live in the service layer
(app.services.query_execution / app.services.sandbox_refresh); this module
holds no db import, matching app.domain.scenario's convention.

Statement classification (read/write/unknown) is Unit 9's
app.domain.query_classifier and is reused as-is here, not duplicated.
"""

from __future__ import annotations

from enum import Enum

from app.domain.query_classifier import ClassifiedStatement, StatementType

MAX_RESULT_ROWS = 500

# Postgres advisory-lock key shared by app.services.sandbox_refresh (exclusive
# holder, for its whole run) and app.services.query_execution (shared holder,
# for one submission's whole run) - not a random value, an arbitrary but
# fixed constant so both services agree on the same lock. Advisory locks are
# session-scoped at the database level, not per-role, so this correctly
# serializes across the owner and meadowops_sandbox connections alike, and
# (unlike app.api.query_playground's old in-process threading.Lock) across
# multiple worker processes too.
SANDBOX_ADVISORY_LOCK_KEY = 872_234_501


class QuerySubmissionStatus(str, Enum):
    RECEIVED = "received"
    CONFIRMATION_REQUIRED = "confirmation_required"
    EXECUTING = "executing"
    SUCCESS = "success"
    ERROR = "error"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


QUERY_SUBMISSION_VALID_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        (QuerySubmissionStatus.RECEIVED.value, QuerySubmissionStatus.CONFIRMATION_REQUIRED.value),
        (QuerySubmissionStatus.RECEIVED.value, QuerySubmissionStatus.EXECUTING.value),
        (
            QuerySubmissionStatus.CONFIRMATION_REQUIRED.value,
            QuerySubmissionStatus.EXECUTING.value,
        ),
        (
            QuerySubmissionStatus.CONFIRMATION_REQUIRED.value,
            QuerySubmissionStatus.CANCELLED.value,
        ),
        (QuerySubmissionStatus.EXECUTING.value, QuerySubmissionStatus.SUCCESS.value),
        (QuerySubmissionStatus.EXECUTING.value, QuerySubmissionStatus.ERROR.value),
        (QuerySubmissionStatus.EXECUTING.value, QuerySubmissionStatus.TIMED_OUT.value),
    }
)


def can_transition_submission(from_status: str, to_status: str) -> bool:
    return (from_status, to_status) in QUERY_SUBMISSION_VALID_TRANSITIONS


class SandboxRefreshStatus(str, Enum):
    RUNNING = "running"
    SWAPPED = "swapped"
    COMPLETE = "complete"
    FAILED = "failed"


SANDBOX_REFRESH_VALID_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        (SandboxRefreshStatus.RUNNING.value, SandboxRefreshStatus.SWAPPED.value),
        (SandboxRefreshStatus.RUNNING.value, SandboxRefreshStatus.FAILED.value),
        (SandboxRefreshStatus.SWAPPED.value, SandboxRefreshStatus.COMPLETE.value),
        (SandboxRefreshStatus.SWAPPED.value, SandboxRefreshStatus.FAILED.value),
    }
)


def can_transition_refresh(from_status: str, to_status: str) -> bool:
    return (from_status, to_status) in SANDBOX_REFRESH_VALID_TRANSITIONS


def truncate_rows(rows: list, limit: int = MAX_RESULT_ROWS) -> tuple[list, bool]:
    """Caps a result set at `limit` rows (PRD 5.9's row-limit control).

    Returns (possibly-truncated rows, whether truncation happened) rather
    than raising - an oversized result set is an expected, handled case
    (9.2: "row-limited/paginated, not rendered in full or crashing the
    browser"), not an error.
    """
    if len(rows) > limit:
        return rows[:limit], True
    return rows, False


def overall_statement_type(classified: list[ClassifiedStatement]) -> str:
    """Summarizes a (possibly multi-statement) submission to one QueryLog
    value. A write anywhere in the submission makes the whole submission
    "write" for logging purposes, even if most statements are reads - same
    fail-toward-the-more-serious-classification bias as
    app.domain.query_classifier.requires_confirmation. Empty input (nothing
    parsed) is "unknown", never defaulted to "read".
    """
    if not classified:
        return "unknown"
    types = {c.statement_type for c in classified}
    if StatementType.WRITE in types:
        return "write"
    if StatementType.UNKNOWN in types:
        return "unknown"
    return "read"
