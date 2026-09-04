"""Unit 18 (MEADOWOPS-DOM-011, business id MEADOWOPS-DOMAIN-009, PRD 6.4):
admin-only scenario builder controls — select/inject/preview/edit/
regenerate/approve/cancel/activate. Every route here is require_admin
(DD-24 point 4): no Analyst read path exists, unlike every other
Subsystem-1-facing resource in this codebase — an undelivered scenario
visible early would spoil it before the Analyst ever receives it.

Routes stay `def`, not `async def`, matching every other route in this
project's sync-SQLAlchemy stack (see app.api.master_data's docstring).

`created_by` is taken from the caller's own verified identity
(require_admin's claims), never from the request body — the Builder
account creating a scenario is the account authenticated on the request,
not a client-supplied value.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from psycopg import errors as pg_errors
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.db.enums import CompetencyCluster, DifficultyTier, ScenarioStatus, ScenarioType
from app.db.scenario import Scenario
from app.db.session import get_session
from app.domain.claude_client import ClaudeClient
from app.domain.scenario import ExceptionFlagNotOpenError
from app.domain.scenario_generation import ScenarioGenerationFailedError
from app.schemas.scenario import (
    GroundTruthUpdate,
    ScenarioCreate,
    ScenarioRead,
)
from app.schemas.scenario import ScenarioStatus as ScenarioStatusLiteral
from app.services.scenario_service import (
    ExceptionFlagNotFoundError,
    ScenarioGenerationValidationError,
    ScenarioNotFoundError,
    ScenarioTransitionError,
    ScenarioValidationError,
    activate_scenario,
    approve_scenario,
    cancel_scenario,
    create_scenario_from_exception_flag,
    get_scenario,
    list_scenarios,
    regenerate_scenario,
    update_ground_truth,
)


def get_claude_client(request: Request) -> ClaudeClient | None:
    """`app.state.claude_client` is `None` until a real Anthropic SDK
    adapter is wired in (Phase 4, blocker B3: no API key configured yet) -
    regenerate_scenario_route below turns that into a clean 503 rather than
    calling the service layer with nothing to call Claude through."""
    return request.app.state.claude_client

router = APIRouter(prefix="/api/v1/admin/scenarios", tags=["admin-scenarios"])


@router.get("", response_model=list[ScenarioRead])
def list_scenarios_route(
    status_filter: ScenarioStatusLiteral | None = None,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_admin),
) -> list[Scenario]:
    # ScenarioStatusLiteral (schemas/scenario.py) is a Pydantic Literal, so
    # FastAPI 422s an invalid value before this ever runs — security review
    # of this unit flagged the earlier `ScenarioStatus(status_filter)` form
    # (a bare-str query param fed straight to the enum constructor) as an
    # unhandled ValueError -> 500 on any bad value.
    parsed_status = ScenarioStatus(status_filter) if status_filter else None
    return list_scenarios(session, status=parsed_status)


@router.get("/{scenario_id}", response_model=ScenarioRead)
def get_scenario_route(
    scenario_id: uuid.UUID,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_admin),
) -> Scenario:
    try:
        return get_scenario(session, scenario_id)
    except ScenarioNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("", response_model=ScenarioRead, status_code=status.HTTP_201_CREATED)
def create_scenario_route(
    payload: ScenarioCreate,
    session: Session = Depends(get_session),
    identity: dict[str, str] = Depends(require_admin),
) -> Scenario:
    try:
        # A validly-signed token's `sub` claim is always a real UUID string
        # today (app.api.auth mints it from user.id) — guarded anyway
        # (security review, LOW) so a malformed/future claim shape 401s
        # instead of an unhandled ValueError -> 500.
        created_by = uuid.UUID(identity["user_id"])
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        ) from exc
    try:
        # create_scenario_from_exception_flag flushes internally (assigns
        # the new row's id) — a FK violation on created_by therefore raises
        # here, at the service call, not later at session.commit() below.
        scenario = create_scenario_from_exception_flag(
            session,
            exception_flag_id=payload.exception_flag_id,
            scenario_type=ScenarioType(payload.scenario_type),
            competency_cluster=CompetencyCluster(payload.competency_cluster),
            difficulty_tier=DifficultyTier(payload.difficulty_tier),
            title=payload.title,
            created_by=created_by,
        )
    except ExceptionFlagNotFoundError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ExceptionFlagNotOpenError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except IntegrityError as exc:
        session.rollback()
        # Code review, MEDIUM: a still-valid session token whose user row
        # was since deleted/deactivated-and-removed hits created_by's hard
        # FK to live.user.id here — same IntegrityError->409 convention
        # app.api.master_data's create_record already uses, rather than an
        # unhandled 500.
        if isinstance(exc.orig, pg_errors.ForeignKeyViolation):
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="Creating user account no longer exists"
            ) from exc
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Scenario violates a constraint"
        ) from exc
    session.commit()
    session.refresh(scenario)
    return scenario


@router.patch("/{scenario_id}/ground-truth", response_model=ScenarioRead)
def update_ground_truth_route(
    scenario_id: uuid.UUID,
    payload: GroundTruthUpdate,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_admin),
) -> Scenario:
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    try:
        scenario = update_ground_truth(session, scenario_id, updates)
    except ScenarioNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ScenarioTransitionError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()
    session.refresh(scenario)
    return scenario


@router.post("/{scenario_id}/regenerate", response_model=ScenarioRead)
def regenerate_scenario_route(
    scenario_id: uuid.UUID,
    session: Session = Depends(get_session),
    claude_client: ClaudeClient | None = Depends(get_claude_client),
    _identity: dict[str, str] = Depends(require_admin),
) -> Scenario:
    if claude_client is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scenario narrative generation is not configured (no Claude client)",
        )
    try:
        scenario = regenerate_scenario(session, scenario_id, claude_client)
    except ScenarioNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ExceptionFlagNotFoundError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ExceptionFlagNotOpenError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except ScenarioTransitionError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ScenarioGenerationFailedError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except ScenarioGenerationValidationError as exc:
        session.rollback()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"errors": exc.errors}
        ) from exc
    session.commit()
    session.refresh(scenario)
    return scenario


@router.post("/{scenario_id}/approve", response_model=ScenarioRead)
def approve_scenario_route(
    scenario_id: uuid.UUID,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_admin),
) -> Scenario:
    try:
        scenario = approve_scenario(session, scenario_id)
    except ScenarioNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ScenarioTransitionError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ScenarioValidationError as exc:
        session.rollback()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"errors": exc.errors}
        ) from exc
    session.commit()
    session.refresh(scenario)
    return scenario


@router.post("/{scenario_id}/activate", response_model=ScenarioRead)
def activate_scenario_route(
    scenario_id: uuid.UUID,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_admin),
) -> Scenario:
    try:
        scenario = activate_scenario(session, scenario_id)
    except ScenarioNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ScenarioTransitionError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()
    session.refresh(scenario)
    return scenario


@router.post("/{scenario_id}/cancel", response_model=ScenarioRead)
def cancel_scenario_route(
    scenario_id: uuid.UUID,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_admin),
) -> Scenario:
    try:
        scenario = cancel_scenario(session, scenario_id)
    except ScenarioNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ScenarioTransitionError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()
    session.refresh(scenario)
    return scenario
