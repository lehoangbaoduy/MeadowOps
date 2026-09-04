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

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.chat import ChatMessage, ChatThread, ChatThreadReadState
from app.db.enums import StakeholderPersona, UserRole

MAX_MESSAGE_BODY_LENGTH = 10_000


class ThreadNotFoundError(ValueError):
    pass


class MessageBodyTooLongError(ValueError):
    pass


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
) -> ChatMessage:
    """Immutability itself is enforced below this layer, at the database
    (migration 0018's trigger) — this function has no update/delete
    counterpart at all, on purpose, matching PRD 6.13/ER-6."""
    get_thread(session, thread_id)
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
    )
    session.add(message)
    session.flush()
    return message


@dataclass(frozen=True)
class ThreadWithUnread:
    thread: ChatThread
    unread_count: int


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
    messages sent after `last_read_at`."""
    read_state = (
        select(ChatThreadReadState.thread_id, ChatThreadReadState.last_read_at)
        .where(ChatThreadReadState.user_id == user_id)
        .subquery()
    )
    unread_count = func.count(ChatMessage.id).filter(
        or_(
            read_state.c.last_read_at.is_(None),
            ChatMessage.sent_at > read_state.c.last_read_at,
        )
    )
    stmt = (
        select(ChatThread, unread_count)
        .outerjoin(read_state, read_state.c.thread_id == ChatThread.id)
        .outerjoin(ChatMessage, ChatMessage.thread_id == ChatThread.id)
        .group_by(ChatThread.id, read_state.c.last_read_at)
        .order_by(ChatThread.created_at)
    )
    return [
        ThreadWithUnread(thread=thread, unread_count=count)
        for thread, count in session.execute(stmt).all()
    ]
