"""Unit 30c (MEADOWOPS-UI-005, S1-FR-15/PRD 347/380, B12 follow-on to U30):
the transactional layer for uploading and retrieving chat attachments.
Does not commit - caller-owns-the-transaction, same convention as every
other service module in this project.

`storage` (app.core.storage.AttachmentStorage) is always an explicit
parameter, never imported/constructed here - same dependency-injection
convention app.services.persona_chat/scenario_generation already use for
ClaudeClient, so this module stays testable against a fake storage without
touching the filesystem.

Deliberately its own module, not folded into app.services.chat: uploading
and retrieving attachment bytes is a distinct I/O concern (object storage,
not just Postgres) from message send/receive, and only send_message (in
app.services.chat) needs to know an attachment exists at all.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.storage import AttachmentStorage
from app.db.chat import ChatAttachment, ChatMessage
from app.db.enums import ChatThreadStatus
from app.domain.attachment_validation import validate_attachment_content
from app.services.chat import ThreadCompletedError, get_thread


class AttachmentTooLargeError(ValueError):
    pass


class AttachmentRecordMissingError(ValueError):
    """Raised by get_attachment_for_message for either of two
    should-never-happen broken states: a message's attachment_ref points
    at a ChatAttachment row that doesn't exist at all, or (security review,
    this unit) one that exists but whose own message_id doesn't point back
    at this message. Both are unreachable through send_message's normal
    claim path (attachment_ref and message_id are only ever set together,
    under a row lock - see app.services.chat.send_message's own docstring),
    checked anyway per this project's established defense-in-depth-for-an-
    unreachable-case precedent."""


def upload_attachment(
    session: Session,
    storage: AttachmentStorage,
    *,
    thread_id: uuid.UUID,
    uploaded_by_user_id: uuid.UUID,
    original_filename: str,
    claimed_content_type: str,
    content: bytes,
    max_size_bytes: int,
) -> ChatAttachment:
    """Validates, stores the bytes, and records the metadata row - in that
    order, so a rejected upload (too large, wrong type) never touches
    storage or the database at all.

    Unlike send_message, this does not itself enforce Analyst-only - that's
    app.api.chat's require_analyst dependency (a route-layer auth concern,
    same split every other write in this project uses: the route derives
    and trusts the caller's identity, the service trusts what it's given,
    per app.services.chat's own module docstring)."""
    thread = get_thread(session, thread_id)
    if thread.status == ChatThreadStatus.COMPLETED:
        raise ThreadCompletedError(f"chat thread {thread_id} is already completed")
    if len(content) > max_size_bytes:
        raise AttachmentTooLargeError(
            f"attachment exceeds the {max_size_bytes}-byte size cap"
        )
    sniffed_content_type = validate_attachment_content(claimed_content_type, content)
    storage_key = uuid.uuid4().hex
    storage.save(storage_key, content)
    attachment = ChatAttachment(
        thread_id=thread_id,
        uploaded_by_user_id=uploaded_by_user_id,
        storage_key=storage_key,
        original_filename=original_filename,
        content_type=sniffed_content_type,
        size_bytes=len(content),
        created_at=datetime.now(timezone.utc),
    )
    session.add(attachment)
    session.flush()
    return attachment


def get_attachment_for_message(
    session: Session, message_id: uuid.UUID
) -> ChatAttachment | None:
    """Returns the ChatAttachment backing this message, or None if the
    message has no attachment (including if the message itself doesn't
    exist - callers distinguish "no message" from "no attachment" by
    looking up the message separately first, same as app.services.chat's
    own get_thread-then-act pattern).

    Raises AttachmentRecordMissingError for either of two genuinely-broken
    states, neither reachable through send_message's normal claim path
    (attachment_ref and message_id are only ever set together, under a row
    lock - see app.services.chat.send_message's own docstring) but checked
    rather than trusted, matching this project's established defense-in-
    depth-for-an-unreachable-case precedent: (1) attachment_ref points at a
    row that doesn't exist at all, or (2) that row exists but its own
    message_id points at a different message than this one (security
    review, this unit - added alongside send_message's with_for_update
    claim lock: trusting attachment_ref alone, without this check, would
    let two messages both resolve to and serve the same file if a future
    code path ever set attachment_ref outside that locked claim step)."""
    message = session.get(ChatMessage, message_id)
    if message is None or message.attachment_ref is None:
        return None
    attachment = session.get(ChatAttachment, uuid.UUID(message.attachment_ref))
    if attachment is None:
        raise AttachmentRecordMissingError(
            f"message {message_id} references attachment {message.attachment_ref}, "
            "which does not exist"
        )
    if attachment.message_id != message_id:
        raise AttachmentRecordMissingError(
            f"message {message_id} references attachment {message.attachment_ref}, "
            f"but that attachment's own message_id points at {attachment.message_id} instead"
        )
    return attachment
