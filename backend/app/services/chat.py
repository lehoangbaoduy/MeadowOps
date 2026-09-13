"""Unit 21a (MEADOWOPS-DOM-014, PRD 6.13, DD-25): chat — the transactional
layer over `chat.chat_thread`/`chat.chat_message`. Does not commit —
caller-owns-the-transaction, same convention as every other service module
in this project (app.api.chat commits after each call).

`sender_user_id`/`sender_role` are parameters this module trusts as given,
never re-derived here — deriving them from the caller's verified session
(never a request body) is app.api.chat's job specifically, so that
guarantee is provable at the one layer that actually sees raw HTTP input,
matching how app.api.admin_scenarios.create_scenario_route (not
app.services.scenario_service) is the one that turns `identity["user_id"]`
into `created_by`.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.chat import ChatAttachment, ChatMessage, ChatThread, ChatThreadDraft, ChatThreadReadState
from app.db.enums import ChatThreadStatus, StakeholderPersona, UserRole

MAX_MESSAGE_BODY_LENGTH = 10_000
# Unit 30a (MEADOWOPS-UI-003, PRD 6.1): "Response windows: default 3-5
# real-world days per round" - the PRD gives a range, not one number; this
# mirrors Settings.chat_response_window_days's own default (app.core.
# config), which app.api.chat passes through explicitly rather than this
# module importing Settings itself (same convention as app.services.ledger.
# flag_stale's after_days parameter).
DEFAULT_RESPONSE_WINDOW_DAYS = 4


class ThreadNotFoundError(ValueError):
    pass


class MessageBodyTooLongError(ValueError):
    pass


class ThreadCompletedError(ValueError):
    """Unit 25 (MEADOWOPS-DOM-019, PRD 6.6 step 8): "the Analyst's most
    recent message is the submission of record" - a message sent after a
    thread is marked Completed would silently change what that record is,
    without ever re-running the evaluation it was graded against. Raised
    by send_message once ChatThreadStatus.COMPLETED is set."""


class AttachmentNotFoundError(ValueError):
    """Unit 30c (MEADOWOPS-UI-005): raised by send_message when the given
    attachment_id doesn't correspond to any ChatAttachment row."""


class AttachmentOwnershipError(ValueError):
    """Unit 30c (MEADOWOPS-UI-005): raised by send_message when the given
    attachment was uploaded by a different user, or to a different thread,
    than the message now trying to claim it. This is also what structurally
    keeps attachments Analyst-side-only (S1-FR-15) without send_message
    needing its own role check - the upload route (require_analyst) is the
    only way an attachment row's uploaded_by_user_id is ever set, so a
    Builder-sent message can never satisfy this check against their own
    user_id."""


class AttachmentAlreadyLinkedError(ValueError):
    """Unit 30c (MEADOWOPS-UI-005): raised by send_message when the given
    attachment already backs a different message - the app-level half of
    the "one attachment, at most one message" invariant (migration 0026's
    message_id UNIQUE constraint is the DB-level half).

    Comment correction (dual review, this unit): an earlier version of this
    docstring claimed the UNIQUE constraint was a backstop against a
    concurrent-claim race on the same attachment_id - both reviewers traced
    that this is false. Two concurrent sends claiming the same attachment
    write two different message_id values to the *same* row (an ordinary
    last-writer-wins UPDATE, not a cross-row uniqueness conflict), so the
    UNIQUE constraint never engages for this particular race. What actually
    closes it now is the `with_for_update=True` row lock send_message takes
    when it fetches the attachment - the second concurrent caller blocks
    until the first commits, then sees message_id already set and raises
    this error for real, rather than both silently succeeding."""


def get_or_create_thread(
    session: Session, *, scenario_id: uuid.UUID, persona: StakeholderPersona
) -> ChatThread:
    """DD-25: one thread per (scenario, persona) pair for its whole life —
    the Builder picks *which* thread to open, never spins up a second one
    for a persona already in play on this scenario. Idempotent rather than
    erroring on a repeat call, since "open the CFO thread" is a perfectly
    normal thing to do twice."""
    existing = session.scalar(
        select(ChatThread).where(
            ChatThread.scenario_id == scenario_id, ChatThread.persona == persona
        )
    )
    if existing is not None:
        return existing
    thread = ChatThread(scenario_id=scenario_id, persona=persona)
    session.add(thread)
    session.flush()
    return thread


def list_threads(session: Session) -> list[ChatThread]:
    """No per-role filtering here — DD-25's "Analyst sees a unified inbox,
    not scenario-labeled" is a presentation choice for U21's frontend, not
    a server-side boundary; nothing in a thread's own identity (scenario_id,
    persona) is more sensitive than any other Subsystem-1-readable data
    (pre-implementation security review of this unit)."""
    return list(
        session.scalars(select(ChatThread).order_by(ChatThread.created_at))
    )


def get_thread(session: Session, thread_id: uuid.UUID) -> ChatThread:
    thread = session.get(ChatThread, thread_id)
    if thread is None:
        raise ThreadNotFoundError(f"chat thread {thread_id} not found")
    return thread


def list_messages(session: Session, thread_id: uuid.UUID) -> list[ChatMessage]:
    get_thread(session, thread_id)
    return list(
        session.scalars(
            select(ChatMessage)
            .where(ChatMessage.thread_id == thread_id)
            .order_by(ChatMessage.sent_at)
        )
    )


def send_message(
    session: Session,
    *,
    thread_id: uuid.UUID,
    sender_user_id: uuid.UUID,
    sender_role: UserRole,
    body: str,
    response_window_days: int = DEFAULT_RESPONSE_WINDOW_DAYS,
    attachment_id: uuid.UUID | None = None,
) -> ChatMessage:
    """Immutability itself is enforced below this layer, at the database
    (migration 0018's trigger) — this function has no update/delete
    counterpart at all, on purpose, matching PRD 6.13/ER-6.

    Unit 30c (MEADOWOPS-UI-005): attachment_id, when given, must already
    exist as an unclaimed ChatAttachment row uploaded by sender_user_id on
    this exact thread_id - see AttachmentOwnershipError's own docstring for
    why that ownership check is also the entire mechanism keeping
    attachments Analyst-side-only. Claimed (attachment.message_id set) only
    after the message itself is successfully created, in the same
    transaction - see migration 0026's docstring for why this can't be set
    at ChatMessage INSERT time via a column on ChatMessage itself."""
    thread = get_thread(session, thread_id)
    attachment: ChatAttachment | None = None
    if attachment_id is not None:
        # with_for_update (security review, this unit): without a row lock
        # here, two concurrent sends of the same attachment_id (double-click
        # send, or a client retry after a slow/ambiguous response - no
        # adversarial timing needed) can both read message_id IS NULL, both
        # pass the check below, and both successfully claim it, silently
        # breaking the "at most one message" invariant migration 0026
        # documents. This blocks the second concurrent caller until the
        # first transaction commits or rolls back, so it then sees the
        # already-set message_id and raises AttachmentAlreadyLinkedError for
        # real instead of racing past this check.
        attachment = session.get(ChatAttachment, attachment_id, with_for_update=True)
        if attachment is None:
            raise AttachmentNotFoundError(f"attachment {attachment_id} not found")
        if attachment.thread_id != thread_id or attachment.uploaded_by_user_id != sender_user_id:
            raise AttachmentOwnershipError(
                f"attachment {attachment_id} was not uploaded by {sender_user_id} "
                f"on thread {thread_id}"
            )
        if attachment.message_id is not None:
            raise AttachmentAlreadyLinkedError(
                f"attachment {attachment_id} already backs message {attachment.message_id}"
            )
    # Unit 25 (MEADOWOPS-DOM-019, security review, LOW): once a thread is
    # Completed, its evaluation has already been generated against "the
    # Analyst's most recent message" at that moment (PRD 6.6 step 8) - a
    # later message would silently outrun that record without ever
    # re-triggering evaluation (complete_thread_and_generate_evaluation
    # already refuses a second call via ThreadAlreadyCompletedError).
    if thread.status == ChatThreadStatus.COMPLETED:
        raise ThreadCompletedError(f"chat thread {thread_id} is already completed")
    # Defense in depth alongside app.schemas.chat.MessageCreate's own
    # max_length (pre-implementation security review, LOW): this is the one
    # choke point every send goes through regardless of caller, and it's
    # also what app.api.chat broadcasts verbatim to every live WS
    # connection — an unbounded body is an unbounded broadcast frame, not
    # just an unbounded row.
    if len(body) > MAX_MESSAGE_BODY_LENGTH:
        raise MessageBodyTooLongError(
            f"message body exceeds {MAX_MESSAGE_BODY_LENGTH} characters"
        )
    message = ChatMessage(
        thread_id=thread_id,
        sender_user_id=sender_user_id,
        sender_role=sender_role,
        body=body,
        attachment_ref=str(attachment_id) if attachment_id is not None else None,
    )
    session.add(message)
    if attachment is not None:
        # Must happen after message exists (message.id is server-generated
        # at INSERT) - flushed below, before claiming.
        session.flush()
        attachment.message_id = message.id
    # Unit 30a (MEADOWOPS-UI-003, PRD 6.1, B12): a Builder message starts
    # the Analyst's response window; an Analyst reply satisfies it. Reset
    # both idempotency flags on every set/clear either way (see ChatThread.
    # deadline_approaching_notified's own docstring) - a fresh round is
    # eligible for its own sweep_thread_deadlines notifications again.
    if sender_role == UserRole.ANALYST:
        thread.deadline_at = None
    else:
        thread.deadline_at = datetime.now(timezone.utc) + timedelta(days=response_window_days)
    thread.deadline_approaching_notified = False
    thread.overdue_notified = False
    # Unit 30b (MEADOWOPS-UI-004, PRD 6.1, B12): once this send succeeds,
    # whatever the sender had drafted for this thread is now sent - clear
    # it in the same transaction rather than relying on a separate client
    # call, so there's no window where a failed clear leaves stale text
    # behind after a successful send. Deliberately scoped to
    # sender_user_id only - the other role's own draft on this same
    # thread (see ChatThreadDraft's own docstring on why drafts are
    # per-user) is untouched.
    session.execute(
        delete(ChatThreadDraft).where(
            ChatThreadDraft.thread_id == thread_id, ChatThreadDraft.user_id == sender_user_id
        )
    )
    session.flush()
    return message


def save_draft(session: Session, *, thread_id: uuid.UUID, user_id: uuid.UUID, body: str) -> None:
    """Unit 30b (MEADOWOPS-UI-004, PRD 6.1 'Drafting' bullet, catalog row
    31, B12): upsert-or-delete, not insert-only - "save my draft" is
    called on every debounced composer change, not once per (thread,
    user) pair ever, the same "mark read is called every time" reasoning
    mark_thread_read's own docstring gives for its upsert. A blank (or
    whitespace-only) body means "no draft" (ChatThreadDraft's own
    docstring: a row here means unsent text exists), so the row is
    deleted rather than stored empty. Same MAX_MESSAGE_BODY_LENGTH cap as
    send_message itself (defense in depth) - a draft is potential message
    text, no reason to let it grow past what could ever actually be
    sent."""
    get_thread(session, thread_id)
    if len(body) > MAX_MESSAGE_BODY_LENGTH:
        raise MessageBodyTooLongError(
            f"draft body exceeds {MAX_MESSAGE_BODY_LENGTH} characters"
        )
    if body.strip() == "":
        session.execute(
            delete(ChatThreadDraft).where(
                ChatThreadDraft.thread_id == thread_id, ChatThreadDraft.user_id == user_id
            )
        )
        return
    stmt = pg_insert(ChatThreadDraft).values(
        thread_id=thread_id, user_id=user_id, body=body, updated_at=func.clock_timestamp()
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[ChatThreadDraft.thread_id, ChatThreadDraft.user_id],
        set_={"body": stmt.excluded.body, "updated_at": stmt.excluded.updated_at},
    )
    session.execute(stmt)


@dataclass(frozen=True)
class ThreadWithUnread:
    thread: ChatThread
    unread_count: int
    # Unit 30b (MEADOWOPS-UI-004, PRD 6.1, B12): this user's own not-yet-
    # sent draft for this thread ("" if none) - piggybacked onto the same
    # per-user thread listing rather than a separate per-thread GET, since
    # the frontend already fetches this whole list before a composer for
    # any one thread is ever opened.
    draft_body: str = ""


def mark_thread_read(session: Session, *, thread_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Unit 21 (MEADOWOPS-DOM-015, S1-FR-15): upsert, not insert — "mark
    read" is called every time a user opens/refreshes a thread, not once
    per (thread, user) pair ever. `chat.chat_thread_read_state` (migration
    0019) is a separate, ordinary mutable table specifically because
    ChatMessage's own immutability trigger would reject exactly this kind
    of frequent update."""
    get_thread(session, thread_id)
    # clock_timestamp(), not now(): Postgres's now()/CURRENT_TIMESTAMP is
    # transaction-time, frozen at the transaction's first statement — the
    # same value ChatMessage.sent_at's own server_default=func.now() would
    # produce for a message inserted in the *same* transaction, which would
    # make an "arrived after this read" message compare equal to, not
    # greater than, last_read_at instead of strictly after it.
    # clock_timestamp() is real statement-time, matching "the instant this
    # mark-read call actually happened" regardless of transaction framing.
    stmt = pg_insert(ChatThreadReadState).values(
        thread_id=thread_id, user_id=user_id, last_read_at=func.clock_timestamp()
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[ChatThreadReadState.thread_id, ChatThreadReadState.user_id],
        set_={"last_read_at": stmt.excluded.last_read_at},
    )
    session.execute(stmt)


def list_threads_with_unread(session: Session, *, user_id: uuid.UUID) -> list[ThreadWithUnread]:
    """One query, not N+1 (code-review precedent: U16's own MEDIUM fix for
    exactly this pattern) — a thread with no read-state row for this user
    is fully unread (every message counts), one with a row only counts
    messages sent after `last_read_at`. Unit 30b (MEADOWOPS-UI-004, B12)
    adds a second, independent outer join for this same user's own draft
    (empty string when no ChatThreadDraft row exists) - filtered by
    user_id the same way read_state already is, so this never returns the
    other role's draft for a thread they share."""
    read_state = (
        select(ChatThreadReadState.thread_id, ChatThreadReadState.last_read_at)
        .where(ChatThreadReadState.user_id == user_id)
        .subquery()
    )
    draft_state = (
        select(ChatThreadDraft.thread_id, ChatThreadDraft.body)
        .where(ChatThreadDraft.user_id == user_id)
        .subquery()
    )
    unread_count = func.count(ChatMessage.id).filter(
        or_(
            read_state.c.last_read_at.is_(None),
            ChatMessage.sent_at > read_state.c.last_read_at,
        )
    )
    stmt = (
        select(ChatThread, unread_count, draft_state.c.body)
        .outerjoin(read_state, read_state.c.thread_id == ChatThread.id)
        .outerjoin(ChatMessage, ChatMessage.thread_id == ChatThread.id)
        .outerjoin(draft_state, draft_state.c.thread_id == ChatThread.id)
        .group_by(ChatThread.id, read_state.c.last_read_at, draft_state.c.body)
        .order_by(ChatThread.created_at)
    )
    return [
        ThreadWithUnread(thread=thread, unread_count=count, draft_body=draft_body or "")
        for thread, count, draft_body in session.execute(stmt).all()
    ]
