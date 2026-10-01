"""Unit 30a (MEADOWOPS-UI-003, PRD 6.1/6.13, B12 follow-on to U30):
app.services.notifications - the Notification CRUD surface plus
sweep_thread_deadlines, the scheduler-tick-driven producer of
DEADLINE_APPROACHING/DEADLINE_MISSED rows. Same non-autocommit, real-DB,
per-test-rollback discipline as tests/services/test_chat_service.py.
"""

import os
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.db.auth import User
from app.db.chat import ChatMessage, Notification
from app.db.enums import (
    CompetencyCluster,
    DifficultyTier,
    NotificationKind,
    ScenarioStatus,
    ScenarioType,
    StakeholderPersona,
    UserRole,
)
from app.db.exception_flags import ExceptionFlag
from app.db.scenario import Scenario
from app.services.baseline_data import seed_master_data
from app.services.chat import delete_thread, get_or_create_thread, mark_thread_read, send_message
from app.services.exception_rule_defaults import seed_exception_rule_thresholds
from app.services.notifications import (
    NotificationNotFoundError,
    create_notification,
    list_notification_feed,
    list_notifications_for_user,
    mark_notification_read,
    sweep_thread_deadlines,
)
from app.services.scenario_service import create_scenario_from_exception_flag

_PRODUCT_ID = "SKU-COR-001"
_WAREHOUSE_ID = "WH-EAST"
_ADMIN_EMAIL = "zztest-notif-admin@meadowops.local"
_ANALYST_EMAIL = "zztest-notif-analyst@meadowops.local"


@pytest.fixture
def session():
    engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
    with Session(engine) as session:
        session.execute(delete(User).where(User.email.in_([_ADMIN_EMAIL, _ANALYST_EMAIL])))
        session.commit()
        seed_master_data(session)
        seed_exception_rule_thresholds(session)
        session.commit()
        yield session
        session.rollback()
        session.execute(delete(User).where(User.email.in_([_ADMIN_EMAIL, _ANALYST_EMAIL])))
        session.commit()
    engine.dispose()


@pytest.fixture
def admin_id(session: Session) -> uuid.UUID:
    user = User(email=_ADMIN_EMAIL, password_hash="x", role=UserRole.ADMIN, is_active=True)
    session.add(user)
    session.flush()
    return user.id


@pytest.fixture
def analyst_id(session: Session) -> uuid.UUID:
    user = User(email=_ANALYST_EMAIL, password_hash="x", role=UserRole.ANALYST, is_active=True)
    session.add(user)
    session.flush()
    return user.id


@pytest.fixture
def scenario_id(session: Session, admin_id: uuid.UUID) -> uuid.UUID:
    flag = ExceptionFlag(
        category="low_stock_days_of_supply",
        product_id=_PRODUCT_ID,
        warehouse_id=_WAREHOUSE_ID,
        simulation_date=date(2026, 6, 1),
        first_detected_simulation_date=date(2026, 5, 20),
        measured_value=Decimal("4.00"),
        threshold_value=Decimal("10.00"),
    )
    session.add(flag)
    session.flush()
    scenario: Scenario = create_scenario_from_exception_flag(
        session,
        exception_flag_id=flag.id,
        scenario_type=ScenarioType.DATA_QUALITY_ISSUE,
        competency_cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS,
        difficulty_tier=DifficultyTier.STANDARD,
        title="zztest notification scenario",
        created_by=admin_id,
    )
    return scenario.id


class TestNotificationCrud:
    def test_create_and_list_notifications_for_a_user(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        create_notification(
            session, user_id=admin_id, thread_id=thread.id, kind=NotificationKind.DEADLINE_MISSED
        )
        session.flush()
        notifications = list_notifications_for_user(session, user_id=admin_id)
        assert len(notifications) == 1
        assert notifications[0].thread_id == thread.id
        assert notifications[0].kind == NotificationKind.DEADLINE_MISSED
        assert notifications[0].read_at is None

    def test_list_notifications_is_scoped_to_the_requesting_user_only(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        create_notification(
            session, user_id=admin_id, thread_id=thread.id, kind=NotificationKind.DEADLINE_MISSED
        )
        session.flush()
        assert list_notifications_for_user(session, user_id=analyst_id) == []

    def test_mark_notification_read_sets_read_at(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        notification = create_notification(
            session, user_id=admin_id, thread_id=thread.id, kind=NotificationKind.DEADLINE_MISSED
        )
        session.flush()
        mark_notification_read(session, notification_id=notification.id, user_id=admin_id)
        session.flush()
        session.refresh(notification)
        assert notification.read_at is not None

    def test_mark_notification_read_raises_for_an_unknown_id(
        self, session: Session, admin_id: uuid.UUID
    ) -> None:
        with pytest.raises(NotificationNotFoundError):
            mark_notification_read(session, notification_id=uuid.uuid4(), user_id=admin_id)

    def test_mark_notification_read_raises_when_the_notification_belongs_to_someone_else(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        """Ownership-scoped lookup (id AND user_id together), not a
        separate existence check then a 403 - a wrong-owner id 404s exactly
        like an unknown one, so this never becomes an oracle for whether a
        given notification id exists at all."""
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        notification = create_notification(
            session, user_id=admin_id, thread_id=thread.id, kind=NotificationKind.DEADLINE_MISSED
        )
        session.flush()
        with pytest.raises(NotificationNotFoundError):
            mark_notification_read(session, notification_id=notification.id, user_id=analyst_id)

    def test_the_limit_never_truncates_an_unread_row_behind_read_ones(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        """Advisor review (this unit): role-wide fan-out plus no retention
        policy means a user's read history can eventually push past
        DEFAULT_NOTIFICATION_LIST_LIMIT. Unread-first ordering means the
        limit can only ever truncate already-seen rows - this pins that
        with limit=1: the single oldest notification is still unread, and
        it must still be the one returned, not the newer already-read one."""
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        old_unread = create_notification(
            session, user_id=admin_id, thread_id=thread.id, kind=NotificationKind.DEADLINE_MISSED
        )
        new_read = create_notification(
            session,
            user_id=admin_id,
            thread_id=thread.id,
            kind=NotificationKind.DEADLINE_APPROACHING,
        )
        session.flush()
        # Postgres now() is frozen at transaction start (same reason
        # mark_thread_read needs func.clock_timestamp() - see that
        # function's own comment), so both rows get an identical
        # created_at unless backdated explicitly: this pins both sort
        # keys (unread-first, then created_at) rather than only the
        # first one.
        old_unread.created_at = datetime.now(timezone.utc) - timedelta(days=2)
        session.flush()
        mark_notification_read(session, notification_id=new_read.id, user_id=admin_id)
        session.flush()

        notifications = list_notifications_for_user(session, user_id=admin_id, limit=1)
        assert len(notifications) == 1
        assert notifications[0].id == old_unread.id
        assert notifications[0].read_at is None


class TestSweepThreadDeadlines:
    """Catalog row 15 (deadline passes with no response -> Builder
    notified, doesn't vanish) and row 30's notification half (scheduler
    downtime recovers cleanly - no double-fires, no lost events)."""

    def test_an_overdue_thread_notifies_the_builder_and_flags_overdue(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        send_message(
            session, thread_id=thread.id, sender_user_id=admin_id,
            sender_role=UserRole.ADMIN, body="VP wants a status update",
        )
        session.refresh(thread)
        thread.deadline_at = datetime.now(timezone.utc) - timedelta(hours=1)
        session.flush()

        sweep_thread_deadlines(
            session, now=datetime.now(timezone.utc), approaching_within=timedelta(hours=24)
        )
        session.refresh(thread)
        assert thread.overdue_notified is True

        notifications = list_notifications_for_user(session, user_id=admin_id)
        assert len(notifications) == 1
        assert notifications[0].kind == NotificationKind.DEADLINE_MISSED
        assert notifications[0].thread_id == thread.id

    def test_a_deleted_thread_is_never_swept(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        send_message(
            session, thread_id=thread.id, sender_user_id=admin_id,
            sender_role=UserRole.ADMIN, body="VP wants a status update",
        )
        session.refresh(thread)
        thread.deadline_at = datetime.now(timezone.utc) - timedelta(hours=1)
        session.flush()
        delete_thread(session, thread.id)

        sweep_thread_deadlines(
            session, now=datetime.now(timezone.utc), approaching_within=timedelta(hours=24)
        )
        assert list_notifications_for_user(session, user_id=admin_id) == []

    def test_notifications_for_a_deleted_thread_are_not_listed(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        # Code review (Unit 37): the thread 404s once deleted, so a listed
        # notification would pin the unread badge and open a dead link.
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        create_notification(
            session, user_id=admin_id, thread_id=thread.id, kind=NotificationKind.DEADLINE_MISSED
        )
        session.flush()
        assert len(list_notifications_for_user(session, user_id=admin_id)) == 1
        delete_thread(session, thread.id)
        assert list_notifications_for_user(session, user_id=admin_id) == []

    def test_sweeping_an_already_overdue_thread_twice_does_not_double_fire(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        """Row 30: a scheduler restart re-running the sweep against
        already-flagged state must be a no-op, not a second notification."""
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        send_message(
            session, thread_id=thread.id, sender_user_id=admin_id,
            sender_role=UserRole.ADMIN, body="VP wants a status update",
        )
        session.refresh(thread)
        thread.deadline_at = datetime.now(timezone.utc) - timedelta(hours=1)
        session.flush()

        now = datetime.now(timezone.utc)
        sweep_thread_deadlines(session, now=now, approaching_within=timedelta(hours=24))
        sweep_thread_deadlines(session, now=now, approaching_within=timedelta(hours=24))

        notifications = list_notifications_for_user(session, user_id=admin_id)
        assert len(notifications) == 1

    def test_a_thread_approaching_its_deadline_notifies_the_analyst(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        send_message(
            session, thread_id=thread.id, sender_user_id=admin_id,
            sender_role=UserRole.ADMIN, body="VP wants a status update",
        )
        session.refresh(thread)
        thread.deadline_at = datetime.now(timezone.utc) + timedelta(hours=1)
        session.flush()

        sweep_thread_deadlines(
            session, now=datetime.now(timezone.utc), approaching_within=timedelta(hours=24)
        )
        session.refresh(thread)
        assert thread.deadline_approaching_notified is True
        assert thread.overdue_notified is False

        notifications = list_notifications_for_user(session, user_id=analyst_id)
        assert len(notifications) == 1
        assert notifications[0].kind == NotificationKind.DEADLINE_APPROACHING

    def test_a_thread_not_yet_approaching_gets_no_notification(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        send_message(
            session, thread_id=thread.id, sender_user_id=admin_id,
            sender_role=UserRole.ADMIN, body="VP wants a status update",
            response_window_days=4,
        )
        # deadline_at is ~4 days out, well past the 24h approaching window
        sweep_thread_deadlines(
            session, now=datetime.now(timezone.utc), approaching_within=timedelta(hours=24)
        )
        assert list_notifications_for_user(session, user_id=analyst_id) == []
        assert list_notifications_for_user(session, user_id=admin_id) == []

    def test_a_thread_with_no_deadline_is_skipped(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        get_or_create_thread(session, scenario_id=scenario_id, persona=StakeholderPersona.CFO)
        sweep_thread_deadlines(
            session, now=datetime.now(timezone.utc), approaching_within=timedelta(hours=24)
        )
        assert list_notifications_for_user(session, user_id=admin_id) == []
        assert list_notifications_for_user(session, user_id=analyst_id) == []

    def test_a_completed_thread_is_never_swept(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        """A thread that reached Completed before its deadline passed
        isn't "still open with no response" - PRD 6.1's late-handling
        concept doesn't apply to work that's already done."""
        from app.db.enums import ChatThreadStatus

        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        send_message(
            session, thread_id=thread.id, sender_user_id=admin_id,
            sender_role=UserRole.ADMIN, body="VP wants a status update",
        )
        session.refresh(thread)
        thread.deadline_at = datetime.now(timezone.utc) - timedelta(hours=1)
        thread.status = ChatThreadStatus.COMPLETED
        session.flush()

        sweep_thread_deadlines(
            session, now=datetime.now(timezone.utc), approaching_within=timedelta(hours=24)
        )
        assert list_notifications_for_user(session, user_id=admin_id) == []

    def test_a_thread_already_flagged_approaching_still_gets_missed_once_overdue(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        """The overdue check is deliberately independent of
        deadline_approaching_notified (app.services.notifications.
        sweep_thread_deadlines) - a thread that already got its
        DEADLINE_APPROACHING notification must still get DEADLINE_MISSED
        once its deadline actually passes. This is the normal lifecycle
        (approaching, then missed) rather than the double-fire-prevention
        case the other tests cover."""
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        send_message(
            session, thread_id=thread.id, sender_user_id=admin_id,
            sender_role=UserRole.ADMIN, body="VP wants a status update",
        )
        session.refresh(thread)
        thread.deadline_at = datetime.now(timezone.utc) + timedelta(hours=1)
        session.flush()
        sweep_thread_deadlines(
            session, now=datetime.now(timezone.utc), approaching_within=timedelta(hours=24)
        )
        session.refresh(thread)
        assert thread.deadline_approaching_notified is True
        assert thread.overdue_notified is False

        thread.deadline_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        session.flush()
        sweep_thread_deadlines(
            session, now=datetime.now(timezone.utc), approaching_within=timedelta(hours=24)
        )
        session.refresh(thread)
        assert thread.overdue_notified is True

        analyst_notifications = list_notifications_for_user(session, user_id=analyst_id)
        admin_notifications = list_notifications_for_user(session, user_id=admin_id)
        assert [n.kind for n in analyst_notifications] == [NotificationKind.DEADLINE_APPROACHING]
        assert [n.kind for n in admin_notifications] == [NotificationKind.DEADLINE_MISSED]


class TestNotificationFeed:
    """Unit 39 (MEADOWOPS-DOM-027): what a user actually has to be told about
    - deadline notifications plus replies from the other side they have not
    read yet. An empty feed is what makes the header badge disappear."""

    def _thread(self, session: Session, scenario_id: uuid.UUID):
        return get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )

    def test_is_empty_when_there_is_nothing_to_notify_about(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        self._thread(session, scenario_id)
        assert list_notification_feed(session, user_id=admin_id) == []

    def test_an_unread_reply_from_the_other_side_is_a_new_reply_item(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        thread = self._thread(session, scenario_id)
        send_message(
            session, thread_id=thread.id, sender_user_id=analyst_id,
            sender_role=UserRole.ANALYST, body="Here is my analysis",
        )
        send_message(
            session, thread_id=thread.id, sender_user_id=analyst_id,
            sender_role=UserRole.ANALYST, body="And a follow-up",
        )

        feed = list_notification_feed(session, user_id=admin_id)

        assert len(feed) == 1
        item = feed[0]
        assert item.kind == "new_reply"
        assert item.thread_id == thread.id
        assert item.persona == StakeholderPersona.CFO
        assert item.scenario_title == "zztest notification scenario"
        assert item.unread_count == 2
        assert item.is_read is False

    def test_a_users_own_messages_never_notify_them(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        thread = self._thread(session, scenario_id)
        send_message(
            session, thread_id=thread.id, sender_user_id=admin_id,
            sender_role=UserRole.ADMIN, body="Opening message",
        )
        assert list_notification_feed(session, user_id=admin_id) == []

    def test_reading_the_thread_clears_the_reply_item(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        thread = self._thread(session, scenario_id)
        send_message(
            session, thread_id=thread.id, sender_user_id=analyst_id,
            sender_role=UserRole.ANALYST, body="Here is my analysis",
        )
        mark_thread_read(session, thread_id=thread.id, user_id=admin_id)
        session.flush()
        assert list_notification_feed(session, user_id=admin_id) == []

    def test_a_reply_arriving_after_the_last_read_is_unread_again(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        thread = self._thread(session, scenario_id)
        send_message(
            session, thread_id=thread.id, sender_user_id=analyst_id,
            sender_role=UserRole.ANALYST, body="first",
        )
        mark_thread_read(session, thread_id=thread.id, user_id=admin_id)
        session.flush()
        # now() is frozen at transaction start, so a second send_message in
        # this single test transaction would not land after the read's
        # clock_timestamp(); insert it with an explicit later sent_at.
        session.add(
            ChatMessage(
                thread_id=thread.id, sender_user_id=analyst_id, sender_role=UserRole.ANALYST,
                body="second", sent_at=datetime.now(timezone.utc) + timedelta(seconds=5),
            )
        )
        session.flush()

        feed = list_notification_feed(session, user_id=admin_id)

        assert [(i.kind, i.unread_count) for i in feed] == [("new_reply", 1)]

    def test_a_deadline_notification_appears_with_its_read_state(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        thread = self._thread(session, scenario_id)
        unread = create_notification(
            session, user_id=admin_id, thread_id=thread.id, kind=NotificationKind.DEADLINE_MISSED
        )
        session.flush()

        feed = list_notification_feed(session, user_id=admin_id)
        assert [(i.kind, i.is_read) for i in feed] == [("deadline_missed", False)]
        assert feed[0].id == str(unread.id)

        mark_notification_read(session, notification_id=unread.id, user_id=admin_id)
        feed = list_notification_feed(session, user_id=admin_id)
        assert [(i.kind, i.is_read) for i in feed] == [("deadline_missed", True)]

    def test_unread_items_come_before_read_ones(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        thread = self._thread(session, scenario_id)
        old = create_notification(
            session, user_id=admin_id, thread_id=thread.id, kind=NotificationKind.DEADLINE_MISSED
        )
        session.flush()
        mark_notification_read(session, notification_id=old.id, user_id=admin_id)
        send_message(
            session, thread_id=thread.id, sender_user_id=analyst_id,
            sender_role=UserRole.ANALYST, body="reply",
        )

        feed = list_notification_feed(session, user_id=admin_id)

        assert [i.kind for i in feed] == ["new_reply", "deadline_missed"]

    def test_a_deleted_thread_contributes_nothing(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        thread = self._thread(session, scenario_id)
        send_message(
            session, thread_id=thread.id, sender_user_id=analyst_id,
            sender_role=UserRole.ANALYST, body="reply",
        )
        create_notification(
            session, user_id=admin_id, thread_id=thread.id, kind=NotificationKind.DEADLINE_MISSED
        )
        session.flush()
        delete_thread(session, thread.id)
        assert list_notification_feed(session, user_id=admin_id) == []


class TestCancelledScenarioStaysQuiet:
    """Unit 39: removing (cancelling) a scenario must silence it. Its threads
    are kept for the record, but they may not keep raising deadline
    notifications or unread-reply badges for a scenario nobody is working."""

    def _cancel(self, session: Session, scenario_id: uuid.UUID) -> None:
        scenario = session.get(Scenario, scenario_id)
        scenario.status = ScenarioStatus.CANCELLED
        session.flush()

    def test_a_cancelled_scenarios_overdue_thread_is_never_swept(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        send_message(
            session, thread_id=thread.id, sender_user_id=admin_id,
            sender_role=UserRole.ADMIN, body="VP wants a status update",
        )
        session.refresh(thread)
        thread.deadline_at = datetime.now(timezone.utc) - timedelta(hours=1)
        session.flush()
        self._cancel(session, scenario_id)

        counts = sweep_thread_deadlines(
            session, now=datetime.now(timezone.utc), approaching_within=timedelta(hours=24)
        )

        assert counts == {"approaching": 0, "missed": 0}
        assert list_notifications_for_user(session, user_id=admin_id) == []

    def test_notifications_raised_before_the_cancel_disappear_from_the_feed(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        create_notification(
            session, user_id=admin_id, thread_id=thread.id, kind=NotificationKind.DEADLINE_MISSED
        )
        session.flush()
        assert len(list_notification_feed(session, user_id=admin_id)) == 1

        self._cancel(session, scenario_id)

        assert list_notifications_for_user(session, user_id=admin_id) == []
        assert list_notification_feed(session, user_id=admin_id) == []

    def test_an_unread_reply_on_a_cancelled_scenario_is_not_a_notification(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        send_message(
            session, thread_id=thread.id, sender_user_id=analyst_id,
            sender_role=UserRole.ANALYST, body="Here is my analysis",
        )
        assert len(list_notification_feed(session, user_id=admin_id)) == 1

        self._cancel(session, scenario_id)

        assert list_notification_feed(session, user_id=admin_id) == []
