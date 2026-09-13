"""Unit 24 (MEADOWOPS-DOM-018, business id MEADOWOPS-DOMAIN-013, PRD 4.4):
Decision & Event Ledger API. Write routes are require_admin (PRD 376:
"restrict write operations on master data and all admin panel controls to
the Admin (Builder) role"), the same DD-24 point 4 convention
app.api.admin_scenarios already follows.

Read routes are require_authenticated, not require_admin — unlike U23's
chat pushback/sufficiency routes, nothing on the ledger is ground-truth
secret from the Analyst (PRD Appendix D.1 maps an Activity/Ledger view to
orbynadmin; S1-FR-8 needs scenario generation to reference prior outcomes
for continuity). This also makes the callback-candidates route reachable by
Subsystem 2's internal-service credential
(app.core.internal_client/app.services.subsystem2.ledger_client) — the
whole point of this unit's callback mechanism — without needing a
reject_service_role opt-out the way Query Playground's routes do
(tests/architecture/test_subsystem_boundary.py pins this route
classification explicitly, same discipline as that file's chat/query
allowlists).

`decided_by` is taken from the caller's own verified identity
(require_admin's claims), never from the request body — same convention as
admin_scenarios.py's `created_by`.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import errors as pg_errors
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import require_admin, require_authenticated
from app.db.ledger import ApprovalAuthority, DecisionEvent, DecisionOutcome, EntityType, RecordType
from app.db.session import get_session
from app.domain.ledger import DecisionEventStatus
from app.schemas.ledger import (
    DecisionAcceptRequest,
    DecisionOutcomeRequest,
    DecisionProposeRequest,
    DecisionRead,
)
from app.schemas.ledger import DecisionEventStatus as DecisionEventStatusLiteral
from app.schemas.ledger import EntityType as EntityTypeLiteral
from app.services.ledger import (
    DecisionEventNotFoundError,
    DecisionTransitionError,
    accept_decision,
    find_callback_candidates,
    get_decision,
    list_decisions,
    mark_implemented,
    mark_partially_implemented,
    propose_decision,
    record_outcome,
    reject_decision,
    request_clarification,
    resubmit_decision,
)

router = APIRouter(prefix="/api/v1/ledger", tags=["ledger"])


@router.post("/decisions", response_model=DecisionRead, status_code=status.HTTP_201_CREATED)
def propose_decision_route(
    payload: DecisionProposeRequest,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_admin),
) -> DecisionEvent:
    try:
        decision = propose_decision(
            session,
            entity_type=EntityType(payload.entity_type),
            entity_id=payload.entity_id,
            title=payload.title,
            summary=payload.summary,
            record_type=RecordType(payload.record_type),
            scenario_id=payload.scenario_id,
            approval_authority=ApprovalAuthority(payload.approval_authority)
            if payload.approval_authority
            else None,
            supersedes_id=payload.supersedes_id,
        )
    except IntegrityError as exc:
        session.rollback()
        # Code review, HIGH: supersedes_id is a real hard FK
        # (app.db.ledger.DecisionEvent.supersedes_id) but only
        # UUID-format-validated by the schema, not existence-checked - a
        # well-formed but unknown id used to reach here as an unhandled
        # IntegrityError -> 500. Same IntegrityError->409 convention
        # app.api.admin_scenarios.create_scenario_route already uses for
        # its own created_by FK.
        if isinstance(exc.orig, pg_errors.ForeignKeyViolation):
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="supersedes_id does not reference a known decision"
            ) from exc
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Decision violates a constraint"
        ) from exc
    session.commit()
    session.refresh(decision)
    return decision


@router.post("/decisions/{decision_id}/request-clarification", response_model=DecisionRead)
def request_clarification_route(
    decision_id: uuid.UUID,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_admin),
) -> DecisionEvent:
    try:
        decision = request_clarification(session, decision_id)
    except DecisionEventNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DecisionTransitionError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()
    session.refresh(decision)
    return decision


@router.post("/decisions/{decision_id}/resubmit", response_model=DecisionRead)
def resubmit_decision_route(
    decision_id: uuid.UUID,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_admin),
) -> DecisionEvent:
    try:
        decision = resubmit_decision(session, decision_id)
    except DecisionEventNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DecisionTransitionError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()
    session.refresh(decision)
    return decision


@router.post("/decisions/{decision_id}/accept", response_model=DecisionRead)
def accept_decision_route(
    decision_id: uuid.UUID,
    payload: DecisionAcceptRequest,
    session: Session = Depends(get_session),
    identity: dict[str, str] = Depends(require_admin),
) -> DecisionEvent:
    try:
        decision = accept_decision(
            session,
            decision_id,
            decided_by=identity["user_id"],
            approval_authority=ApprovalAuthority(payload.approval_authority)
            if payload.approval_authority
            else None,
        )
    except DecisionEventNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DecisionTransitionError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()
    session.refresh(decision)
    return decision


@router.post("/decisions/{decision_id}/reject", response_model=DecisionRead)
def reject_decision_route(
    decision_id: uuid.UUID,
    session: Session = Depends(get_session),
    identity: dict[str, str] = Depends(require_admin),
) -> DecisionEvent:
    try:
        decision = reject_decision(session, decision_id, decided_by=identity["user_id"])
    except DecisionEventNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DecisionTransitionError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()
    session.refresh(decision)
    return decision


@router.post("/decisions/{decision_id}/implement", response_model=DecisionRead)
def mark_implemented_route(
    decision_id: uuid.UUID,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_admin),
) -> DecisionEvent:
    try:
        decision = mark_implemented(session, decision_id)
    except DecisionEventNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DecisionTransitionError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()
    session.refresh(decision)
    return decision


@router.post("/decisions/{decision_id}/partially-implement", response_model=DecisionRead)
def mark_partially_implemented_route(
    decision_id: uuid.UUID,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_admin),
) -> DecisionEvent:
    try:
        decision = mark_partially_implemented(session, decision_id)
    except DecisionEventNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DecisionTransitionError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()
    session.refresh(decision)
    return decision


@router.post("/decisions/{decision_id}/outcome", response_model=DecisionRead)
def record_outcome_route(
    decision_id: uuid.UUID,
    payload: DecisionOutcomeRequest,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_admin),
) -> DecisionEvent:
    try:
        decision = record_outcome(
            session, decision_id, outcome=DecisionOutcome(payload.outcome), notes=payload.notes
        )
    except DecisionEventNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DecisionTransitionError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()
    session.refresh(decision)
    return decision


@router.get("/decisions", response_model=list[DecisionRead])
def list_decisions_route(
    status_filter: DecisionEventStatusLiteral | None = None,
    entity_type: EntityTypeLiteral | None = None,
    entity_id: str | None = None,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_authenticated),
) -> list[DecisionEvent]:
    return list_decisions(
        session,
        status=DecisionEventStatus(status_filter) if status_filter else None,
        entity_type=EntityType(entity_type) if entity_type else None,
        entity_id=entity_id,
    )


@router.get("/decisions/{decision_id}", response_model=DecisionRead)
def get_decision_route(
    decision_id: uuid.UUID,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_authenticated),
) -> DecisionEvent:
    try:
        return get_decision(session, decision_id)
    except DecisionEventNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/entities/{entity_type}/{entity_id}/callback-candidates", response_model=list[DecisionRead])
def callback_candidates_route(
    entity_type: EntityTypeLiteral,
    entity_id: str,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_authenticated),
) -> list[DecisionEvent]:
    return find_callback_candidates(session, entity_type=EntityType(entity_type), entity_id=entity_id)
