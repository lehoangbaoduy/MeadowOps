"""Request/response schemas for Unit 26's portfolio mechanism (PRD 6.10).

`PortfolioReflectionRead` (the response to authoring a reflection)
deliberately carries only the seven reflection fields plus id/thread_id/
created_at - no evaluation, no tier, nothing ER-5 says must stay hidden
from the Analyst during normal use. `PortfolioExportRead` (the compiled
document) is the one place those two do appear together, and that route is
require_admin-only (app.api.portfolio) for exactly that reason.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.evaluation import DifficultyRecommendation
from app.schemas.human_review import HumanReviewVerdict
from app.services.portfolio import MAX_REFLECTION_ANSWER_LENGTH

_ReflectionField = Field(min_length=1, max_length=MAX_REFLECTION_ANSWER_LENGTH)


class PortfolioReflectionCreate(BaseModel):
    reflection_what_happened: str = _ReflectionField
    reflection_initial_thought: str = _ReflectionField
    reflection_evidence_that_mattered: str = _ReflectionField
    reflection_what_missed: str = _ReflectionField
    reflection_what_changed_after_pushback: str = _ReflectionField
    reflection_what_differently: str = _ReflectionField
    reflection_skill_improved: str = _ReflectionField


class PortfolioReflectionRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    thread_id: uuid.UUID
    reflection_what_happened: str
    reflection_initial_thought: str
    reflection_evidence_that_mattered: str
    reflection_what_missed: str
    reflection_what_changed_after_pushback: str
    reflection_what_differently: str
    reflection_skill_improved: str
    created_at: datetime


class _PortfolioScenarioSummary(BaseModel):
    title: str
    scenario_type: str
    competency_cluster: str


class _PortfolioMessage(BaseModel):
    sender_role: Literal["admin", "analyst"]
    body: str
    sent_at: datetime


class _PortfolioEvaluation(BaseModel):
    id: uuid.UUID
    prompt_version: str
    strengths: str
    gaps: str
    evidence: str
    senior_analyst_pushback: str
    final_verdict: str
    suggested_next_skill_focus: str
    difficulty_recommendation: DifficultyRecommendation
    created_at: datetime


class _PortfolioHumanReview(BaseModel):
    reviewer_name: str
    verdict: HumanReviewVerdict
    tier_assessment_notes: str
    overridden_recommendation: DifficultyRecommendation | None
    created_at: datetime


class _PortfolioReflectionSummary(BaseModel):
    reflection_what_happened: str
    reflection_initial_thought: str
    reflection_evidence_that_mattered: str
    reflection_what_missed: str
    reflection_what_changed_after_pushback: str
    reflection_what_differently: str
    reflection_skill_improved: str
    created_at: datetime


class PortfolioExportRead(BaseModel):
    scenario: _PortfolioScenarioSummary
    trigger: str | None
    messages: list[_PortfolioMessage]
    evaluation: _PortfolioEvaluation
    # Both legitimately absent - PRD 1.6 requires neither a completed
    # monthly review nor real portfolio content for Done.
    human_review: _PortfolioHumanReview | None
    reflection: _PortfolioReflectionSummary | None
