"""Unit 19 (MEADOWOPS-DOMAIN-010, spec MEADOWOPS-DOM-012, PRD 5.9/S1-FR-13/
14): the SQL Query Playground's execution, confirmation, refresh, and
history routes. `reject_service_role` (built on `require_authenticated`) on
every route here, not `require_admin` - PRD 5.9: "a page where the Analyst
(or the Builder, during testing) can write and run any SQL"; unlike Unit
18's Builder-only scenario controls, this feature is explicitly for both
roles.

Unit 20 (MEADOWOPS-API-004): every route here uses `reject_service_role`,
not bare `require_authenticated` - `execute_query_route` can commit
confirmed writes against the sandbox schema, and `refresh_sandbox_route`
runs as the *owner* role, unconditionally. Neither is the pure read Unit
20's internal Subsystem 2 service credential is meant for (DD-2, PRD 376/
S1-FR-6 - Subsystem 2 *reads* Subsystem 1's data, it doesn't execute SQL of
its own choosing through it), and pre-implementation security review of
that unit found relying on `_user_id_from_identity`'s incidental UUID-parse
failure as a backstop left a real hole here: `execute_query_route` runs and
commits the submitted SQL *before* it ever touches `identity`, and
`refresh_sandbox_route` never parses `identity` into a UUID at all - so the
service credential's non-UUID user_id would 401 too late, after the side
effect already happened, or not at all.

Routes stay `def`, not `async def` - the sync psycopg connections
app.services.query_execution/sandbox_refresh open would block the event
loop under `async def`, same reasoning app.api.master_data's docstring
already gives for this whole codebase.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import reject_service_role
from app.db.base import Base
from app.db.query_log import QueryLog
from app.db.session import get_session
from app.schemas.query_playground import (
    QueryConfirmationRequiredResponse,
    QueryExecuteResponse,
    QueryLogRead,
    QueryStatementPreview,
    QuerySubmitRequest,
    SandboxRefreshResponse,
)
from app.services.query_execution import (
    QueryConfirmationRequiredError,
    execute_submission,
)
from app.services.query_log import log_cancelled, log_execution
from app.services.sandbox_refresh import refresh_sandbox

router = APIRouter(prefix="/api/v1/query", tags=["query-playground"])
logger = logging.getLogger(__name__)

# Security review: a prior in-process threading.Lock here only 409'd a
# second concurrent refresh *request*; it never protected two refreshes
# racing each other at the service layer, and wouldn't have serialized at
# all across multiple worker processes. app.services.sandbox_refresh now
# holds a Postgres advisory lock for its whole run instead, which
# serializes correctly regardless of caller or process - nothing extra is
# needed at this layer.


def _user_id_from_identity(identity: dict[str, str]) -> uuid.UUID:
    """A validly-signed token's `sub` claim is always a real UUID string
    today (app.api.auth mints it from user.id) - guarded anyway (same
    defense-in-depth Unit 18's create_scenario_route already applies) so a
    malformed/future claim shape 401s instead of an unhandled ValueError ->
    500."""
    try:
        return uuid.UUID(identity["user_id"])
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        ) from exc


@router.post(
    "/execute",
    response_model=QueryExecuteResponse | QueryConfirmationRequiredResponse,
)
def execute_query_route(
    payload: QuerySubmitRequest,
    request: Request,
    session: Session = Depends(get_session),
    identity: dict[str, str] = Depends(reject_service_role),
):
    settings = request.app.state.settings
    try:
        result = execute_submission(
            settings.sandbox_dsn(),
            payload.sql,
            confirmed=payload.confirmed,
            timeout_seconds=settings.query_timeout_seconds,
        )
    except QueryConfirmationRequiredError as exc:
        return QueryConfirmationRequiredResponse(
            statements=[
                QueryStatementPreview(sql=c.sql, statement_type=c.statement_type.value)
                for c in exc.classified
            ]
        )

    log_execution(
        session, user_id=_user_id_from_identity(identity), sql=payload.sql, result=result
    )
    session.commit()
    return QueryExecuteResponse(
        status=result.status,
        columns=result.columns,
        rows=result.rows,
        row_count=result.row_count,
        truncated=result.truncated,
        duration_ms=result.duration_ms,
        error_message=result.error_message,
    )


@router.post("/cancel-confirmation", status_code=status.HTTP_204_NO_CONTENT)
def cancel_confirmation_route(
    payload: QuerySubmitRequest,
    session: Session = Depends(get_session),
    identity: dict[str, str] = Depends(reject_service_role),
) -> None:
    log_cancelled(session, user_id=_user_id_from_identity(identity), sql=payload.sql)
    session.commit()


@router.post("/refresh-sandbox", response_model=SandboxRefreshResponse)
def refresh_sandbox_route(
    request: Request,
    _identity: dict[str, str] = Depends(reject_service_role),
):
    settings = request.app.state.settings
    result = refresh_sandbox(settings.owner_dsn(), Base.metadata)
    error_message = None
    if result.error is not None:
        # Code review: result.error is a raw exception message (potentially
        # exposing table names, connection details, or other internals) -
        # log it server-side only and return a generic message to the
        # client, same principle as _malformed_sql's clean-error handling
        # in app.services.query_execution but for an admin-facing failure
        # that shouldn't leak backend detail either.
        logger.error("Sandbox refresh %s failed: %s", result.id, result.error)
        error_message = "Sandbox refresh failed. Check server logs for details."
    return SandboxRefreshResponse(
        status=result.status.value,
        tables_mirrored=result.tables_mirrored,
        started_at=result.started_at,
        completed_at=result.completed_at,
        error=error_message,
    )


@router.get("/history", response_model=list[QueryLogRead])
def query_history_route(
    session: Session = Depends(get_session),
    identity: dict[str, str] = Depends(reject_service_role),
) -> list[QueryLog]:
    user_id = _user_id_from_identity(identity)
    stmt = (
        select(QueryLog)
        .where(QueryLog.user_id == user_id)
        .order_by(QueryLog.submitted_at.desc())
        .limit(50)
    )
    return list(session.scalars(stmt))
