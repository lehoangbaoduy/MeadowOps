"""Unit 26 (MEADOWOPS-DOM-020, business id MEADOWOPS-DOMAIN-015, PRD 6.6
step 11, ER-1 through ER-6): the transactional layer over
`engine.human_review`. No domain module backs this - unlike app.domain.
evaluation, there is no Claude call and no parsing to unit-test in
isolation, only a straight insert plus the cross-field verdict/
overridden_recommendation pairing already enforced at both the schema
layer (app.schemas.human_review's model_validator) and the database
(migration 0021's CHECK constraint) - this module's own defense-in-depth
re-check is the third layer, same discipline as MAX_MESSAGE_BODY_LENGTH's
schema+service pairing in app.services.chat.

Does not commit - caller-owns-the-transaction, same convention as every
other service module in this project.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import DifficultyRecommendation, HumanReviewVerdict
from app.db.evaluation import Evaluation
from app.db.human_review import HumanReview

MAX_REVIEWER_NAME_LENGTH = 200
MAX_TIER_ASSESSMENT_NOTES_LENGTH = 5_000


class EvaluationNotFoundError(ValueError):
    """Raised when the evaluation_id a human review is being recorded
    against doesn't exist - defense in depth alongside the hard FK
    (app.db.human_review), same "raise, don't bare-assert" precedent
    app.services.evaluation already established for its own scenario
    lookup."""


class HumanReviewAlreadyExistsError(ValueError):
    """Raised when an Evaluation already has a HumanReview attached - PRD
    6.6 step 11 is a single reviewer verdict per sampled evaluation, not a
    repeatable action (same one-per-parent shape as Evaluation itself)."""


class InvalidVerdictPairingError(ValueError):
    """Raised when verdict/overridden_recommendation don't satisfy the
    pairing the schema layer and the database CHECK constraint both also
    enforce (edge case #29: AGREE carries no override, OVERRIDE always
    does) - defense in depth, not the primary guard."""


def record_human_review(
    session: Session,
    *,
    evaluation_id: uuid.UUID,
    submitted_by_user_id: uuid.UUID,
    reviewer_name: str,
    verdict: HumanReviewVerdict,
    tier_assessment_notes: str,
    overridden_recommendation: DifficultyRecommendation | None = None,
) -> HumanReview:
    if session.get(Evaluation, evaluation_id) is None:
        raise EvaluationNotFoundError(f"evaluation {evaluation_id} not found")
    existing = session.scalar(
        select(HumanReview).where(HumanReview.evaluation_id == evaluation_id)
    )
    if existing is not None:
        raise HumanReviewAlreadyExistsError(
            f"evaluation {evaluation_id} already has a human review"
        )
    if verdict == HumanReviewVerdict.AGREE and overridden_recommendation is not None:
        raise InvalidVerdictPairingError(
            "overridden_recommendation must be omitted when verdict is 'agree'"
        )
    if verdict == HumanReviewVerdict.OVERRIDE and overridden_recommendation is None:
        raise InvalidVerdictPairingError(
            "overridden_recommendation is required when verdict is 'override'"
        )
    review = HumanReview(
        evaluation_id=evaluation_id,
        submitted_by_user_id=submitted_by_user_id,
        reviewer_name=reviewer_name,
        verdict=verdict,
        tier_assessment_notes=tier_assessment_notes,
        overridden_recommendation=overridden_recommendation,
    )
    session.add(review)
    session.flush()
    return review


def get_human_review_for_evaluation(
    session: Session, evaluation_id: uuid.UUID
) -> HumanReview | None:
    return session.scalar(select(HumanReview).where(HumanReview.evaluation_id == evaluation_id))
