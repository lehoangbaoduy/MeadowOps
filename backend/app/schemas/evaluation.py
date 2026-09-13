"""Request/response schemas for Unit 25's AI evaluation framework (PRD
6.8) and adaptive difficulty engine (PRD 6.7). No Create schema - every
Evaluation row is produced only by app.services.evaluation.
complete_thread_and_generate_evaluation, never accepted from a request
body (ER-1/ER-6: the AI writes it, never a human, never edited after)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

DifficultyRecommendation = Literal["foundational", "standard", "stretch", "hold"]
CompetencyCluster = Literal["analysis_diagnosis", "judgment_delivery", "communication"]


class EvaluationRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    thread_id: uuid.UUID
    prompt_version: str
    strengths: str
    gaps: str
    evidence: str
    senior_analyst_pushback: str
    final_verdict: str
    suggested_next_skill_focus: str
    difficulty_recommendation: DifficultyRecommendation
    created_at: datetime


class DifficultyRecommendationRead(BaseModel):
    cluster: CompetencyCluster
    recommendation: DifficultyRecommendation
