"""Request/response schemas for Unit 24's Decision & Event Ledger API (PRD
4.4). Create/transition/response schemas kept separate per
schemas/scenario.py's own convention.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

EntityType = Literal["supplier", "warehouse", "product", "customer", "carrier"]
RecordType = Literal["operational_event", "decision"]
DecisionEventStatus = Literal[
    "proposed",
    "clarification_requested",
    "accepted",
    "rejected",
    "implemented",
    "partially_implemented",
    "outcome_observed",
    "stale",
]
ApprovalAuthority = Literal["manager", "procurement_operations", "informational_only"]
DecisionOutcome = Literal[
    "succeeded", "partially_succeeded", "failed", "unintended_consequence", "insufficient_evidence"
]


class DecisionProposeRequest(BaseModel):
    entity_type: EntityType
    entity_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    # Code review, HIGH: `RecordType` (used by DecisionRead below) has a
    # second value, "operational_event" - app.db.ledger's own docstring
    # says only decisions carry the full lifecycle, and nothing in this
    # codebase builds an operational-event creation path yet, so this
    # route structurally can't create one rather than silently accepting
    # a record_type the ledger's own lifecycle machinery (flag_stale,
    # find_callback_candidates) doesn't expect.
    record_type: Literal["decision"] = "decision"
    scenario_id: uuid.UUID | None = None
    approval_authority: ApprovalAuthority | None = None
    supersedes_id: uuid.UUID | None = None


class DecisionAcceptRequest(BaseModel):
    approval_authority: ApprovalAuthority | None = None


class DecisionOutcomeRequest(BaseModel):
    outcome: DecisionOutcome
    notes: str | None = None


class DecisionRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    record_type: RecordType
    status: DecisionEventStatus
    scenario_id: uuid.UUID | None
    entity_type: EntityType
    entity_id: str
    title: str
    summary: str
    proposed_at: datetime
    approval_authority: ApprovalAuthority | None
    decided_at: datetime | None
    decided_by: str | None
    implemented_at: datetime | None
    outcome: DecisionOutcome | None
    outcome_recorded_at: datetime | None
    outcome_notes: str | None
    stale_flagged_at: datetime | None
    supersedes_id: uuid.UUID | None
    created_at: datetime
