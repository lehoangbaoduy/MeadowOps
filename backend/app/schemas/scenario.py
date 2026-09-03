"""Request/response schemas for Unit 18's scenario builder controls (PRD
6.4). Create/Update/Read kept separate per master_data.py's own convention
(coding-style.md: "keep request, update, and response schemas separate").
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ScenarioType = Literal[
    "stakeholder_request",
    "data_quality_issue",
    "root_cause_investigation",
    "supplier_vendor_decision",
    "process_breakdown",
    "executive_reporting",
]
CompetencyCluster = Literal["analysis_diagnosis", "judgment_delivery", "communication"]
DifficultyTier = Literal["foundational", "standard", "stretch"]
ScenarioSource = Literal["exception_flag", "manual"]
ScenarioStatus = Literal["draft", "approved", "active", "cancelled"]


class ScenarioCreate(BaseModel):
    exception_flag_id: uuid.UUID
    scenario_type: ScenarioType
    competency_cluster: CompetencyCluster
    difficulty_tier: DifficultyTier
    title: str = Field(min_length=1)


class GroundTruthUpdate(BaseModel):
    """Partial edit of a draft scenario's ground_truth package (6.4's
    "edit" control) — only the fields present in the payload are merged
    into the existing package, same exclude_unset convention
    app.api.master_data's update_record uses.

    No `evidence` field on purpose (security review): that sub-object is
    the mechanically-derived provenance block (source_exception_flag_id,
    category, dates, measured/threshold values) app.domain.scenario builds
    from the real ExceptionFlag — letting a client overwrite it wholesale
    would let a malformed/incomplete replacement slip past
    validate_for_approval's mere isinstance(dict)-and-non-empty check.
    Builder edits are scoped to the narrative fields; regenerate
    (app.services.scenario_service.regenerate_scenario) is the only way
    evidence itself is ever refreshed."""

    known_cause: str | None = None
    supporting_signals: list[str] | None = None
    distractors: list[str] | None = None
    expected_considerations: list[str] | None = None
    acceptable_conclusions: list[str] | None = None
    unacceptable_conclusions: list[str] | None = None
    uncertainty: str | None = None


class ScenarioRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    title: str
    scenario_type: ScenarioType
    competency_cluster: CompetencyCluster
    difficulty_tier: DifficultyTier
    source: ScenarioSource
    source_exception_flag_id: uuid.UUID | None
    ground_truth: dict
    status: ScenarioStatus
    created_by: uuid.UUID
    approved_at: datetime | None
    activated_at: datetime | None
    created_at: datetime
    updated_at: datetime
