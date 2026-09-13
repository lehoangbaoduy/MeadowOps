"""Request/response schemas for Unit 26's human review mechanism (PRD 6.6
step 11, ER-3/ER-4). Create/Read kept separate, same convention app.
schemas.chat already documents."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.evaluation import DifficultyRecommendation
from app.services.human_review import MAX_REVIEWER_NAME_LENGTH, MAX_TIER_ASSESSMENT_NOTES_LENGTH

HumanReviewVerdict = Literal["agree", "override"]


class HumanReviewCreate(BaseModel):
    reviewer_name: str = Field(min_length=1, max_length=MAX_REVIEWER_NAME_LENGTH)
    verdict: HumanReviewVerdict
    tier_assessment_notes: str = Field(min_length=1, max_length=MAX_TIER_ASSESSMENT_NOTES_LENGTH)
    overridden_recommendation: DifficultyRecommendation | None = None

    @model_validator(mode="after")
    def _check_verdict_recommendation_pairing(self) -> "HumanReviewCreate":
        # Same pairing app.db.human_review's own CHECK constraint enforces
        # at the database layer (migration 0021) - rejected here first so
        # a malformed request never reaches the service/DB layer at all
        # (edge case #29: an override always carries its own call, a
        # simple agreement never does).
        if self.verdict == "agree" and self.overridden_recommendation is not None:
            raise ValueError("overridden_recommendation must be omitted when verdict is 'agree'")
        if self.verdict == "override" and self.overridden_recommendation is None:
            raise ValueError("overridden_recommendation is required when verdict is 'override'")
        return self


class HumanReviewRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    evaluation_id: uuid.UUID
    reviewer_name: str
    verdict: HumanReviewVerdict
    tier_assessment_notes: str
    overridden_recommendation: DifficultyRecommendation | None
    created_at: datetime
