"""Unit 28 (MEADOWOPS-API-005, PRD 6.12/S1-FR-14): admin panel cross-user
visibility into Query Playground activity — "a table of submitted queries
with timestamp, statement type, and result status, expandable to the full
query text ... framed and used as a coaching signal, not a surveillance
one" (PRD 328). Reads live.query_log, written by Unit 19
(MEADOWOPS-DOMAIN-010); no new table or migration.

A separate route from Unit 19's GET /api/v1/query/history, not that route
widened with an admin branch — that route is `reject_service_role` and
self-scoped to the caller, and its safety should stay a property of its
dependency, not a conditional in its body. This one is `require_admin`.

Ordered by (submitted_at desc, id desc), not submitted_at alone —
`QueryLog.submitted_at`'s DB default is `func.now()`, which Postgres
freezes per transaction; rows inserted together (a burst of activity, or a
test fixture) can share an identical timestamp, and id is the tiebreaker
that keeps the ordering (and therefore pagination) a total order rather
than something the DB is free to return in any sequence for tied rows.

Routes stay `def`, not `async def` — same sync-session reasoning
app.api.master_data and app.api.query_playground already give.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.db.auth import User
from app.db.query_log import QueryLog
from app.db.session import get_session
from app.schemas.query_playground import AdminQueryLogRead, QueryLogRead

router = APIRouter(prefix="/api/v1/admin", tags=["admin-query-log"])


@router.get("/query-log", response_model=list[AdminQueryLogRead])
def list_query_log(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_admin),
) -> list[AdminQueryLogRead]:
    rows = session.execute(
        select(QueryLog, User.email)
        .join(User, User.id == QueryLog.user_id)
        .order_by(QueryLog.submitted_at.desc(), QueryLog.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [
        AdminQueryLogRead(**QueryLogRead.model_validate(log).model_dump(), user_email=email)
        for log, email in rows
    ]
