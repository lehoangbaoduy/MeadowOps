"""Unit 26 (MEADOWOPS-DOM-020, business id MEADOWOPS-DOMAIN-015, PRD 6.10):
API surface for the portfolio mechanism.

`record_reflection_route` uses `reject_service_role`, not `require_admin` -
unlike every other route in this unit and Unit 25's evaluation reads, PRD
6.10's seven-question reflection is explicitly written in the Analyst's own
voice ("what I initially thought", "what I missed", "what I'd do
differently") - the same write-access split app.services.chat.send_message
already establishes for the Analyst's own chat replies. Its response
(`PortfolioReflectionRead`) carries no evaluation/tier data at all, so
letting the Analyst read it back leaks nothing ER-5 protects.

`get_portfolio_export_route` is `require_admin` - the compiled document it
returns embeds the full draft evaluation, including
`difficulty_recommendation`, which ER-5 says must stay hidden from the
Analyst outside the monthly reveal.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import errors as pg_errors
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import reject_service_role, require_admin
from app.db.session import get_session
from app.schemas.portfolio import PortfolioExportRead, PortfolioReflectionCreate, PortfolioReflectionRead
from app.services.chat import ThreadNotFoundError
from app.services.portfolio import (
    PortfolioArtifactAlreadyExistsError,
    ThreadNotCompletedError,
    create_portfolio_reflection,
    get_portfolio_export,
)

router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio"])


@router.post(
    "/threads/{thread_id}/reflection",
    response_model=PortfolioReflectionRead,
    status_code=status.HTTP_201_CREATED,
)
def record_reflection_route(
    thread_id: uuid.UUID,
    payload: PortfolioReflectionCreate,
    session: Session = Depends(get_session),
    identity: dict[str, str] = Depends(reject_service_role),
) -> PortfolioReflectionRead:
    try:
        artifact = create_portfolio_reflection(
            session,
            thread_id=thread_id,
            submitted_by_user_id=uuid.UUID(identity["user_id"]),
            reflection_what_happened=payload.reflection_what_happened,
            reflection_initial_thought=payload.reflection_initial_thought,
            reflection_evidence_that_mattered=payload.reflection_evidence_that_mattered,
            reflection_what_missed=payload.reflection_what_missed,
            reflection_what_changed_after_pushback=payload.reflection_what_changed_after_pushback,
            reflection_what_differently=payload.reflection_what_differently,
            reflection_skill_improved=payload.reflection_skill_improved,
        )
        session.commit()
    except ThreadNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ThreadNotCompletedError, PortfolioArtifactAlreadyExistsError) as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IntegrityError as exc:
        # Same DB-level race backstop as Unit 25's /complete route and this
        # unit's own /human-review route - engine.portfolio_artifact's own
        # unique constraint on thread_id closes the concurrent-double-
        # submit race the in-memory check above can't. Code review: narrow
        # to the specific constraint we expect, same as app/api/chat.py's
        # own IntegrityError handlers - anything else re-raises as a 500
        # instead of being misclassified as this conflict.
        session.rollback()
        if isinstance(exc.orig, pg_errors.UniqueViolation):
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="chat thread already has a portfolio reflection"
            ) from exc
        raise
    session.refresh(artifact)
    return artifact


@router.get("/threads/{thread_id}", response_model=PortfolioExportRead)
def get_portfolio_export_route(
    thread_id: uuid.UUID,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_admin),
) -> PortfolioExportRead:
    try:
        return get_portfolio_export(session, thread_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ThreadNotCompletedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
