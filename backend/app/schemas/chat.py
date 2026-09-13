"""Request/response schemas for Unit 21a's chat delivery infrastructure
(PRD 6.13). Create/Read kept separate, same convention app.schemas.scenario
already documents.

Unit 23 adds the persona-roleplay pushback suggestion and AI sufficiency
check schemas at the bottom of this file - Attitude mirrors StakeholderPersona
above it (a Pydantic Literal paralleling a domain enum, app.domain.
persona_chat.Attitude, the same pattern this file already uses for
StakeholderPersona/app.db.enums.StakeholderPersona).
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

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
# Unit 25 (MEADOWOPS-DOM-019) - see app.db.enums.ChatThreadStatus's own
# docstring for why this is two states, not PRD 6.1's full nine.
ThreadStatus = Literal["open", "completed"]
# Unit 30a (MEADOWOPS-UI-003) - see app.db.enums.NotificationKind's own
# docstring for why only two of PRD 6.1's four named notification kinds are
# modeled here.
NotificationKind = Literal["deadline_approaching", "deadline_missed"]


class ThreadCreate(BaseModel):
    scenario_id: uuid.UUID
    persona: StakeholderPersona


class ThreadRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    scenario_id: uuid.UUID
    persona: StakeholderPersona
    status: ThreadStatus
    created_at: datetime
    # Unit 30a (MEADOWOPS-UI-003, PRD 6.1, B12): deadline_at is a plain
    # passthrough of the ORM column; is_overdue is NOT (deadline_at <= now
    # is a moment-of-response computation, not a stored attribute) - both
    # routes that return a ThreadRead/ThreadReadWithUnread build it via
    # app.api.chat._is_overdue rather than declaring a default here.
    deadline_at: datetime | None
    is_overdue: bool


class ThreadReadWithUnread(ThreadRead):
    """Unit 21 (MEADOWOPS-DOM-015, S1-FR-15): the caller's own unread-message
    count for this thread — per-viewer, so this is never a plain
    `from_attributes` read off the ORM object (app.api.chat builds it
    explicitly from app.services.chat.ThreadWithUnread)."""

    unread_count: int
    # Unit 30b (MEADOWOPS-UI-004, PRD 6.1, B12): the caller's own not-yet-
    # sent draft for this thread ("" if none) — per-viewer for the same
    # reason unread_count is, see app.services.chat.ThreadWithUnread.
    draft_body: str = ""


class MessageCreate(BaseModel):
    # Same bounded-input reasoning as LoginRequest (app.api.auth): fast
    # rejection at the schema layer before this ever reaches the service
    # layer's own MAX_MESSAGE_BODY_LENGTH guard (app.services.chat) — kept
    # in sync with that constant rather than a second hardcoded number.
    body: str = Field(min_length=1, max_length=MAX_MESSAGE_BODY_LENGTH)
    # Unit 30c (MEADOWOPS-UI-005, B12): an already-uploaded, not-yet-claimed
    # ChatAttachment's id (see POST /threads/{id}/attachments). Ownership
    # and thread match are verified server-side in
    # app.services.chat.send_message, never trusted from this field alone.
    attachment_id: uuid.UUID | None = None

    @field_validator("body")
    @classmethod
    def _reject_blank_after_strip(cls, value: str) -> str:
        # PRD 9.2 catalog row 16: min_length=1 alone still admits a
        # whitespace-only body (" ") - reject anything that strips to empty.
        if not value.strip():
            raise ValueError("body must not be blank")
        return value


class DraftUpdate(BaseModel):
    # Unit 30b (MEADOWOPS-UI-004, B12): unlike MessageCreate, an empty
    # body is not rejected here - it's the signal that clears a
    # previously-saved draft (app.services.chat.save_draft's own
    # docstring), so no min_length/blank-rejection validator.
    body: str = Field(max_length=MAX_MESSAGE_BODY_LENGTH)


class MessageRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    thread_id: uuid.UUID
    sender_user_id: uuid.UUID
    sender_role: UserRole
    body: str
    attachment_ref: str | None
    sent_at: datetime


class AttachmentRead(BaseModel):
    """Unit 30c (MEADOWOPS-UI-005, B12): the upload route's response - just
    enough for the composer to show what was attached and later pass `id`
    back as MessageCreate.attachment_id. Deliberately excludes storage_key
    (an internal object-store detail, never meant to leave the backend)."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    original_filename: str
    content_type: str
    size_bytes: int
    created_at: datetime


class WsTicketRead(BaseModel):
    ticket: str


class NotificationRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    thread_id: uuid.UUID
    kind: NotificationKind
    created_at: datetime
    read_at: datetime | None


Attitude = Literal["neutral", "frustrated", "urgent", "skeptical", "appreciative"]


class SuggestPushbackRequest(BaseModel):
    attitude: Attitude


class SuggestPushbackResponse(BaseModel):
    suggested_message: str


class SufficiencyCheckResponse(BaseModel):
    verdict: Literal["sufficient", "insufficient"]
    suggested_pushback: str | None
