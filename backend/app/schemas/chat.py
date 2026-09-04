"""Request/response schemas for Unit 21a's chat delivery infrastructure
(PRD 6.13). Create/Read kept separate, same convention app.schemas.scenario
already documents.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.services.chat import MAX_MESSAGE_BODY_LENGTH

StakeholderPersona = Literal[
    "operations_manager",
    "procurement_manager",
    "warehouse_manager",
    "it_manager",
    "operations_director",
    "cfo",
]
UserRole = Literal["admin", "analyst"]


class ThreadCreate(BaseModel):
    scenario_id: uuid.UUID
    persona: StakeholderPersona


class ThreadRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    scenario_id: uuid.UUID
    persona: StakeholderPersona
    created_at: datetime


class ThreadReadWithUnread(ThreadRead):
    """Unit 21 (MEADOWOPS-DOM-015, S1-FR-15): the caller's own unread-message
    count for this thread — per-viewer, so this is never a plain
    `from_attributes` read off the ORM object (app.api.chat builds it
    explicitly from app.services.chat.ThreadWithUnread)."""

    unread_count: int


class MessageCreate(BaseModel):
    # Same bounded-input reasoning as LoginRequest (app.api.auth): fast
    # rejection at the schema layer before this ever reaches the service
    # layer's own MAX_MESSAGE_BODY_LENGTH guard (app.services.chat) — kept
    # in sync with that constant rather than a second hardcoded number.
    body: str = Field(min_length=1, max_length=MAX_MESSAGE_BODY_LENGTH)


class MessageRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    thread_id: uuid.UUID
    sender_user_id: uuid.UUID
    sender_role: UserRole
    body: str
    attachment_ref: str | None
    sent_at: datetime


class WsTicketRead(BaseModel):
    ticket: str
