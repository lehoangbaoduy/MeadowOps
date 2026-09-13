"""Unit 25 (MEADOWOPS-DOM-019, PRD 6.7/6.8/ER-5): read-only surface over the
AI evaluation framework and adaptive difficulty engine.

Every route here is require_admin, not require_authenticated (unlike Unit
24's ledger reads) - PRD ER-5: "Tier and evaluation trend hidden during
normal use, revealed only at monthly review". The Analyst must never reach
either route, and the internal-service credential has no legitimate reason
to either (evaluation is entirely Subsystem 2's own concern, generated and
read within this same process - no cross-subsystem HTTP fetch is needed
here the way Unit 24's ledger_client needed one for Subsystem 1 data).

Unit 26 (MEADOWOPS-DOM-020, PRD 6.6 step 11, ER-3/ER-4) adds the human
review routes at the bottom - also require_admin, for the same ER-5
reasoning: the External Human Reviewer has no account/login of their own
in this phase (PRD 14's Open Items), so the Builder stands in to exercise
the mechanism, the same role QA test-analyst runs already have her play.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import errors as pg_errors
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.db.enums import CompetencyCluster, DifficultyRecommendation, HumanReviewVerdict
from app.db.session import get_session
from app.schemas.evaluation import DifficultyRecommendationRead, EvaluationRead
from app.schemas.human_review import HumanReviewCreate, HumanReviewRead
from app.services.chat import ThreadNotFoundError, get_thread
from app.services.evaluation import get_evaluation_for_thread, resolve_difficulty_for_cluster
from app.services.human_review import (
    EvaluationNotFoundError,
    HumanReviewAlreadyExistsError,
    InvalidVerdictPairingError,
    get_human_review_for_evaluation,
    record_human_review,
)

router = APIRouter(prefix="/api/v1/evaluations", tags=["evaluations"])


@router.get("/threads/{thread_id}", response_model=EvaluationRead)
def get_thread_evaluation_route(
    thread_id: uuid.UUID,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_admin),
) -> EvaluationRead:
    try:
        get_thread(session, thread_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    evaluation = get_evaluation_for_thread(session, thread_id)
    if evaluation is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"no evaluation for chat thread {thread_id}"
        )
    return evaluation


@router.get(
    "/clusters/{cluster}/difficulty-recommendation",
    response_model=DifficultyRecommendationRead,
)
def get_cluster_difficulty_recommendation_route(
    cluster: CompetencyCluster,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_admin),
) -> DifficultyRecommendationRead:
    recommendation = resolve_difficulty_for_cluster(session, cluster)
    return DifficultyRecommendationRead(cluster=cluster.value, recommendation=recommendation.value)


def _get_evaluation_or_404(session: Session, thread_id: uuid.UUID):
    try:
        get_thread(session, thread_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    evaluation = get_evaluation_for_thread(session, thread_id)
    if evaluation is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"no evaluation for chat thread {thread_id}"
        )
    return evaluation


@router.post(
    "/threads/{thread_id}/human-review",
    response_model=HumanReviewRead,
    status_code=status.HTTP_201_CREATED,
)
def record_human_review_route(
    thread_id: uuid.UUID,
    payload: HumanReviewCreate,
    session: Session = Depends(get_session),
    identity: dict[str, str] = Depends(require_admin),
) -> HumanReviewRead:
    evaluation = _get_evaluation_or_404(session, thread_id)
    try:
        review = record_human_review(
            session,
            evaluation_id=evaluation.id,
            submitted_by_user_id=uuid.UUID(identity["user_id"]),
            reviewer_name=payload.reviewer_name,
            verdict=HumanReviewVerdict(payload.verdict),
            tier_assessment_notes=payload.tier_assessment_notes,
            overridden_recommendation=(
                DifficultyRecommendation(payload.overridden_recommendation)
                if payload.overridden_recommendation is not None
                else None
            ),
        )
        session.commit()
    except EvaluationNotFoundError as exc:
        # Unreachable via this route (evaluation was just loaded above) -
        # defense in depth, same class as app.services.evaluation's own
        # ScenarioNotFoundError guard.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (HumanReviewAlreadyExistsError, InvalidVerdictPairingError) as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IntegrityError as exc:
        # Same DB-level race backstop as Unit 25's /complete route - two
        # concurrent human-review submissions for the same evaluation both
        # passing the in-memory HumanReviewAlreadyExistsError check before
        # either commits. engine.human_review's own unique constraint
        # closes it. Code review: narrow to the specific constraint we
        # expect, same as app/api/chat.py's own IntegrityError handlers -
        # anything else re-raises as a 500 instead of being misclassified
        # as this conflict.
        session.rollback()
        if isinstance(exc.orig, pg_errors.UniqueViolation):
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="evaluation already has a human review"
            ) from exc
        raise
    session.refresh(review)
    return review


@router.get("/threads/{thread_id}/human-review", response_model=HumanReviewRead)
def get_human_review_route(
    thread_id: uuid.UUID,
    session: Session = Depends(get_session),
    _identity: dict[str, str] = Depends(require_admin),
) -> HumanReviewRead:
    evaluation = _get_evaluation_or_404(session, thread_id)
    review = get_human_review_for_evaluation(session, evaluation.id)
    if review is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"no human review for chat thread {thread_id}"
        )
    return review
