"""Unit 19 (MEADOWOPS-DOM-012, PRD 5.9/S1-FR-14): persists one QueryLog row
per submission that reached a terminal outcome - never for a submission
still only at the "does this need confirmation" preview step, matching
app.services.query_execution.QueryConfirmationRequiredError's own
docstring on why nothing is logged there.

caller-owns-the-transaction (app.services.exception_engine's convention):
this module flushes but never commits - the API router commits.
"""

import uuid

from sqlalchemy.orm import Session

from app.db.enums import QueryResultStatus, QueryStatementType
from app.db.query_log import QueryLog
from app.domain.query_classifier import classify_submission
from app.domain.query_playground import overall_statement_type
from app.services.query_execution import QueryExecutionResult

# Matches app.db.query_log.QueryLog.error_message's String(2000) column -
# code review: an unbounded assignment would raise a DB-level error on a
# long message (e.g. a verbose Postgres error) and drop the whole audit row
# S1-FR-14 requires, rather than truncating just the one field.
_ERROR_MESSAGE_MAX_LENGTH = 2000


def log_execution(
    session: Session, *, user_id: uuid.UUID, sql: str, result: QueryExecutionResult
) -> QueryLog:
    status_map = {
        "success": QueryResultStatus.SUCCESS,
        "error": QueryResultStatus.ERROR,
        "timed_out": QueryResultStatus.TIMED_OUT,
    }
    entry = QueryLog(
        user_id=user_id,
        query_text=sql,
        statement_type=QueryStatementType(overall_statement_type(classify_submission(sql))),
        result_status=status_map[result.status],
        row_count=result.row_count if result.status == "success" else None,
        duration_ms=result.duration_ms,
        error_message=(
            result.error_message[:_ERROR_MESSAGE_MAX_LENGTH]
            if result.error_message is not None
            else None
        ),
    )
    session.add(entry)
    session.flush()
    return entry


def log_cancelled(session: Session, *, user_id: uuid.UUID, sql: str) -> QueryLog:
    """A submission that needed confirmation and the user explicitly
    declined at the confirmation dialog (S1-FR-14's "executed or
    cancelled")."""
    entry = QueryLog(
        user_id=user_id,
        query_text=sql,
        statement_type=QueryStatementType(overall_statement_type(classify_submission(sql))),
        result_status=QueryResultStatus.CANCELLED,
    )
    session.add(entry)
    session.flush()
    return entry
