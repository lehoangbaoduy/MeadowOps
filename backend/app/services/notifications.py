"""Unit 30a (MEADOWOPS-UI-003, PRD 6.1/6.13, B12 follow-on to U30): the
Notification lifecycle - CRUD over chat.notification, plus
sweep_thread_deadlines, the tick-driven producer of DEADLINE_APPROACHING/
DEADLINE_MISSED rows (wired into app.domain.scheduler._run_tick alongside
app.services.ledger.flag_stale). Does not commit - caller-owns-the-
transaction, same convention as every other service module in this
project.

Deliberately its own module, not folded into app.services.chat: setting/
clearing ChatThread.deadline_at is a side effect of sending a message (that
stays in chat.py's send_message), but the sweep is a background-tick
concern with no request-path caller at all, and Notification CRUD is a
distinct lifecycle (list/mark-read) neither module previously owned.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.auth import User
from app.db.chat import ChatMessage, ChatThread, ChatThreadReadState, Notification
from app.db.enums import (
    ChatThreadStatus,
    NotificationKind,
    ScenarioStatus,
    StakeholderPersona,
    UserRole,
)
from app.db.scenario import Scenario


class NotificationNotFoundError(ValueError):
    pass


def create_notification(
    session: Session, *, user_id: uuid.UUID, thread_id: uuid.UUID, kind: NotificationKind
) -> Notification:
    notification = Notification(user_id=user_id, thread_id=thread_id, kind=kind)
    session.add(notification)
    session.flush()
    return notification


DEFAULT_NOTIFICATION_LIST_LIMIT = 100


def list_notifications_for_user(
    session: Session, *, user_id: uuid.UUID, limit: int = DEFAULT_NOTIFICATION_LIST_LIMIT
) -> list[Notification]:
    """Security review (this unit): unbounded before this limit - a thread
    with a recurring deadline (approaching then missed, every round) plus no
    retention policy meant this grew without bound. A flat LIMIT is the
    right fix over pagination - nothing in this project's notification feed
    needs to page past the most recent N. Unread rows are ordered first
    (advisor review, this unit): with role-wide fan-out (_recipient_ids)
    and no retention policy, a user's read history alone can eventually
    push the LIMIT boundary - ordering unread-before-read means the limit
    can only ever truncate already-seen rows, never hide an unread one
    (short of the user's actual unread count exceeding `limit`, at which
    point there's nothing useful left to show anyway) - preserving catalog
    row 15's "doesn't silently vanish" guarantee."""
    return list(
        session.scalars(
            select(Notification)
            .join(ChatThread, ChatThread.id == Notification.thread_id)
            .join(Scenario, Scenario.id == ChatThread.scenario_id)
            .where(
                Notification.user_id == user_id,
                ChatThread.deleted_at.is_(None),
                # A removed (cancelled) scenario goes quiet: its threads are
                # kept for the record but stop raising notifications.
                Scenario.status != ScenarioStatus.CANCELLED,
            )
            .order_by(Notification.read_at.is_not(None), Notification.created_at.desc())
            .limit(limit)
        )
    )


@dataclass(frozen=True)
class NotificationFeedItem:
    id: str
    kind: str  # "deadline_approaching" | "deadline_missed" | "new_reply"
    thread_id: uuid.UUID
    persona: StakeholderPersona
    scenario_title: str
    unread_count: int  # messages behind a "new_reply"; 0 for deadline items
    occurred_at: datetime
    is_read: bool


def _unread_replies(session: Session, *, user_id: uuid.UUID) -> list[NotificationFeedItem]:
    """One row per live thread holding messages sent by someone else after
    this user last read it. Derived, not stored: reading the thread (the
    existing mark-read call) is what clears it, so the badge can never
    outlive the thing it points at."""
    last_read = (
        select(ChatThreadReadState.thread_id, ChatThreadReadState.last_read_at)
        .where(ChatThreadReadState.user_id == user_id)
        .subquery()
    )
    latest = func.max(ChatMessage.sent_at)
    rows = session.execute(
        select(ChatThread, Scenario.title, func.count(ChatMessage.id), latest)
        .join(ChatMessage, ChatMessage.thread_id == ChatThread.id)
        .join(Scenario, Scenario.id == ChatThread.scenario_id)
        .outerjoin(last_read, last_read.c.thread_id == ChatThread.id)
        .where(
            ChatThread.deleted_at.is_(None),
            Scenario.status != ScenarioStatus.CANCELLED,
            ChatMessage.sender_user_id != user_id,
            or_(last_read.c.last_read_at.is_(None), ChatMessage.sent_at > last_read.c.last_read_at),
        )
        .group_by(ChatThread.id, Scenario.title)
    ).all()
    return [
        NotificationFeedItem(
            id=f"reply:{thread.id}",
            kind="new_reply",
            thread_id=thread.id,
            persona=thread.persona,
            scenario_title=title,
            unread_count=count,
            occurred_at=last_sent,
            is_read=False,
        )
        for thread, title, count, last_sent in rows
    ]


def list_notification_feed(
    session: Session, *, user_id: uuid.UUID, limit: int = DEFAULT_NOTIFICATION_LIST_LIMIT
) -> list[NotificationFeedItem]:
    """Unit 39 (MEADOWOPS-DOM-027): everything this user has to be told about
    - deadline notifications (unread first, as list_notifications_for_user
    already orders them) plus unread replies from the other side. Unread
    items sort before read ones, newest first; an empty feed is what makes
    the header badge disappear."""
    notifications = list_notifications_for_user(session, user_id=user_id, limit=limit)
    thread_info = {
        thread.id: (thread, title)
        for thread, title in session.execute(
            select(ChatThread, Scenario.title)
            .join(Scenario, Scenario.id == ChatThread.scenario_id)
            .where(ChatThread.id.in_({n.thread_id for n in notifications}))
        ).all()
    }
    deadline_items = [
        NotificationFeedItem(
            id=str(n.id),
            kind=n.kind.value,
            thread_id=n.thread_id,
            persona=thread_info[n.thread_id][0].persona,
            scenario_title=thread_info[n.thread_id][1],
            unread_count=0,
            occurred_at=n.created_at,
            is_read=n.read_at is not None,
        )
        for n in notifications
        if n.thread_id in thread_info
    ]
    items = _unread_replies(session, user_id=user_id) + deadline_items
    items.sort(key=lambda item: item.occurred_at, reverse=True)
    items.sort(key=lambda item: item.is_read)  # stable: unread first, newest first within
    return items[:limit]


def mark_notification_read(
    session: Session, *, notification_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Ownership-scoped lookup (id AND user_id together) rather than a
    separate existence check followed by a 403 - a wrong-owner id 404s
    exactly like an unknown one, closing off using this as an oracle for
    whether a given notification id exists at all (pre-implementation
    design review of this unit, same reasoning app.services.chat.
    get_thread already applies to ThreadNotFoundError)."""
    notification = session.scalar(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user_id
        )
    )
    if notification is None:
        raise NotificationNotFoundError(f"notification {notification_id} not found")
    # advisor review (this unit): was `datetime.now(notification.
    # created_at.tzinfo)` - harmless in practice (this function always
    # loads `notification` via a fresh SELECT above, so created_at is
    # always populated) but an unnecessary dependency on a different
    # column's value for something that's always UTC anyway, unlike every
    # other "now" in this module (_is_overdue, sweep_thread_deadlines's
    # own `now` param).
    notification.read_at = datetime.now(timezone.utc)
    session.flush()


def _recipient_ids(session: Session, *, role: UserRole) -> list[uuid.UUID]:
    return list(
        session.scalars(
            select(User.id).where(User.role == role, User.is_active.is_(True))
        )
    )


def sweep_thread_deadlines(
    session: Session, *, now: datetime, approaching_within: timedelta
) -> dict[str, int]:
    """Catalog row 15 (deadline passes with no response -> marked overdue,
    Builder notified, doesn't vanish) and row 30's notification half
    (scheduler downtime recovers cleanly - no double-fires, no lost
    events). Idempotent by construction: each of ChatThread.
    deadline_approaching_notified/overdue_notified is set at most once per
    deadline_at (see that column's own docstring), so re-running this
    sweep against unchanged state - the exact shape of a scheduler
    restart re-processing the same tick - writes nothing a second time.

    Only OPEN threads with a deadline are ever candidates - a Completed
    thread's work is already done regardless of what its stale deadline_at
    still says (app.services.chat.send_message never touches deadline_at
    again once COMPLETED, since ThreadCompletedError blocks any further
    send). Threads of a cancelled scenario are skipped too (Unit 39)."""
    threads = list(
        session.scalars(
            select(ChatThread)
            .join(Scenario, Scenario.id == ChatThread.scenario_id)
            .where(
                ChatThread.status == ChatThreadStatus.OPEN,
                ChatThread.deleted_at.is_(None),
                ChatThread.deadline_at.is_not(None),
                Scenario.status != ScenarioStatus.CANCELLED,
            )
        )
    )
    counts = {"approaching": 0, "missed": 0}
    if not threads:
        return counts

    overdue = [t for t in threads if not t.overdue_notified and t.deadline_at <= now]
    approaching = [
        t
        for t in threads
        if not t.overdue_notified
        and not t.deadline_approaching_notified
        and t.deadline_at > now
        and t.deadline_at - now <= approaching_within
    ]
    if overdue:
        builder_ids = _recipient_ids(session, role=UserRole.ADMIN)
        for thread in overdue:
            for user_id in builder_ids:
                create_notification(
                    session,
                    user_id=user_id,
                    thread_id=thread.id,
                    kind=NotificationKind.DEADLINE_MISSED,
                )
            thread.overdue_notified = True
            counts["missed"] += 1
    if approaching:
        analyst_ids = _recipient_ids(session, role=UserRole.ANALYST)
        for thread in approaching:
            for user_id in analyst_ids:
                create_notification(
                    session,
                    user_id=user_id,
                    thread_id=thread.id,
                    kind=NotificationKind.DEADLINE_APPROACHING,
                )
            thread.deadline_approaching_notified = True
            counts["approaching"] += 1
    session.flush()
    return counts
