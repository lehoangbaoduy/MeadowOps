"""Unit 21a (MEADOWOPS-DOM-014, PRD 6.13, DD-25): chat service layer — the
transactional glue between the real `chat.chat_thread`/`chat.chat_message`
tables and app.api.chat. Same non-autocommit discipline as
tests/services/test_scenario_service.py: runs inside an uncommitted
transaction per test, rolled back at fixture teardown (services never
commit — caller-owns-the-transaction).
"""

import os
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.db.auth import User
from app.db.enums import (
    CompetencyCluster,
    DifficultyTier,
    ScenarioType,
    StakeholderPersona,
    UserRole,
)
from app.db.exception_flags import ExceptionFlag
from app.db.scenario import Scenario
from app.services.baseline_data import seed_master_data
from app.services.chat import (
    MessageBodyTooLongError,
    ThreadNotFoundError,
    get_or_create_thread,
    get_thread,
    list_messages,
    list_threads,
    list_threads_with_unread,
    mark_thread_read,
    send_message,
)
from app.services.exception_rule_defaults import seed_exception_rule_thresholds
from app.services.scenario_service import create_scenario_from_exception_flag

_PRODUCT_ID = "SKU-COR-001"
_WAREHOUSE_ID = "WH-EAST"
_ADMIN_EMAIL = "zztest-chat-admin@meadowops.local"
_ANALYST_EMAIL = "zztest-chat-analyst@meadowops.local"


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
        title="zztest chat scenario",
        created_by=admin_id,
    )
    return scenario.id


class TestGetOrCreateThread:
    def test_creates_a_new_thread(self, session: Session, scenario_id: uuid.UUID) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        assert thread.id is not None
        assert thread.scenario_id == scenario_id
        assert thread.persona == StakeholderPersona.CFO

    def test_is_idempotent_for_the_same_scenario_and_persona(
        self, session: Session, scenario_id: uuid.UUID
    ) -> None:
        """DD-25: one thread per (scenario, persona) pair for its whole
        life — the Builder "picks which thread to open," never creates a
        second one for a persona already in play on this scenario."""
        first = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        second = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        assert first.id == second.id

    def test_different_personas_on_the_same_scenario_get_different_threads(
        self, session: Session, scenario_id: uuid.UUID
    ) -> None:
        cfo_thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        it_thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.IT_MANAGER
        )
        assert cfo_thread.id != it_thread.id


class TestListAndGetThreads:
    def test_list_threads_includes_a_created_thread(
        self, session: Session, scenario_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        assert thread.id in {t.id for t in list_threads(session)}

    def test_get_thread_raises_for_an_unknown_id(self, session: Session) -> None:
        with pytest.raises(ThreadNotFoundError):
            get_thread(session, uuid.uuid4())


class TestSendMessage:
    def test_send_message_records_the_caller_supplied_sender_identity(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        """Sender identity is a parameter this function trusts, not
        something it re-derives — the server-side-derivation guarantee
        (never from a request body) is app.api.chat's job, proven in
        tests/api/test_chat_api.py. This layer's own contract is simpler:
        whatever the caller passes is what gets persisted, verbatim."""
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        message = send_message(
            session,
            thread_id=thread.id,
            sender_user_id=admin_id,
            sender_role=UserRole.ADMIN,
            body="Service level for East is slipping — what's going on?",
        )
        assert message.id is not None
        assert message.sender_user_id == admin_id
        assert message.sender_role == UserRole.ADMIN
        assert message.thread_id == thread.id

    def test_send_message_raises_for_an_unknown_thread(
        self, session: Session, admin_id: uuid.UUID
    ) -> None:
        with pytest.raises(ThreadNotFoundError):
            send_message(
                session,
                thread_id=uuid.uuid4(),
                sender_user_id=admin_id,
                sender_role=UserRole.ADMIN,
                body="hello",
            )

    def test_send_message_rejects_a_body_over_the_length_cap(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        with pytest.raises(MessageBodyTooLongError):
            send_message(
                session,
                thread_id=thread.id,
                sender_user_id=admin_id,
                sender_role=UserRole.ADMIN,
                body="x" * 10_001,
            )

    def test_list_messages_returns_them_in_send_order(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        send_message(
            session, thread_id=thread.id, sender_user_id=admin_id,
            sender_role=UserRole.ADMIN, body="first",
        )
        send_message(
            session, thread_id=thread.id, sender_user_id=analyst_id,
            sender_role=UserRole.ANALYST, body="second",
        )
        bodies = [m.body for m in list_messages(session, thread.id)]
        assert bodies == ["first", "second"]

    def test_list_messages_raises_for_an_unknown_thread(self, session: Session) -> None:
        with pytest.raises(ThreadNotFoundError):
            list_messages(session, uuid.uuid4())


class TestReadState:
    """Unit 21 (MEADOWOPS-DOM-015, S1-FR-15): unread-thread badges — backed
    by chat.chat_thread_read_state (migration 0019), a separate ordinary
    mutable table, not a column on the immutability-trigger-protected
    ChatMessage."""

    def test_mark_thread_read_raises_for_an_unknown_thread(
        self, session: Session, admin_id: uuid.UUID
    ) -> None:
        with pytest.raises(ThreadNotFoundError):
            mark_thread_read(session, thread_id=uuid.uuid4(), user_id=admin_id)

    def test_a_thread_with_no_read_state_is_fully_unread(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        send_message(
            session, thread_id=thread.id, sender_user_id=admin_id,
            sender_role=UserRole.ADMIN, body="first",
        )
        send_message(
            session, thread_id=thread.id, sender_user_id=admin_id,
            sender_role=UserRole.ADMIN, body="second",
        )
        counts = {item.thread.id: item.unread_count for item in list_threads_with_unread(session, user_id=analyst_id)}
        assert counts[thread.id] == 2

    def test_marking_read_zeroes_the_unread_count_for_that_user_only(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        send_message(
            session, thread_id=thread.id, sender_user_id=admin_id,
            sender_role=UserRole.ADMIN, body="hello",
        )
        mark_thread_read(session, thread_id=thread.id, user_id=analyst_id)

        analyst_counts = dict(
            (item.thread.id, item.unread_count) for item in list_threads_with_unread(session, user_id=analyst_id)
        )
        admin_counts = dict(
            (item.thread.id, item.unread_count) for item in list_threads_with_unread(session, user_id=admin_id)
        )
        assert analyst_counts[thread.id] == 0
        assert admin_counts[thread.id] == 1

    # "A message sent after the last read counts as unread, one sent before
    # doesn't" is proven at the API layer instead
    # (tests/api/test_chat_api.py) — Postgres's now()/CURRENT_TIMESTAMP
    # (ChatMessage.sent_at's own server_default) is transaction-time, frozen
    # at BEGIN, so two send_message calls sharing this fixture's one
    # uncommitted transaction always get an identical sent_at regardless of
    # real elapsed time or call order; genuinely distinct timestamps need
    # genuinely separate transactions, which only the real HTTP client
    # (a commit per call, matching production) provides.

    def test_marking_read_twice_is_idempotent_not_an_error(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        send_message(
            session, thread_id=thread.id, sender_user_id=admin_id,
            sender_role=UserRole.ADMIN, body="hello",
        )
        mark_thread_read(session, thread_id=thread.id, user_id=analyst_id)
        mark_thread_read(session, thread_id=thread.id, user_id=analyst_id)
        counts = dict(
            (item.thread.id, item.unread_count) for item in list_threads_with_unread(session, user_id=analyst_id)
        )
        assert counts[thread.id] == 0

    def test_a_thread_with_no_messages_at_all_is_zero_unread(
        self, session: Session, scenario_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        counts = dict(
            (item.thread.id, item.unread_count) for item in list_threads_with_unread(session, user_id=analyst_id)
        )
        assert counts[thread.id] == 0
