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
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.auth import User
from app.db.chat import ChatThread, Notification
from app.db.enums import ChatThreadStatus, NotificationKind, UserRole


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
            .where(Notification.user_id == user_id)
            .order_by(Notification.read_at.is_not(None), Notification.created_at.desc())
            .limit(limit)
        )
    )


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
    send)."""
    threads = list(
        session.scalars(
            select(ChatThread).where(
                ChatThread.status == ChatThreadStatus.OPEN,
                ChatThread.deadline_at.is_not(None),
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
