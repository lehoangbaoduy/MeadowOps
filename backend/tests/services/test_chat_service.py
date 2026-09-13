"""Unit 21a (MEADOWOPS-DOM-014, PRD 6.13, DD-25): chat service layer — the
transactional glue between the real `chat.chat_thread`/`chat.chat_message`
tables and app.api.chat. Same non-autocommit discipline as
tests/services/test_scenario_service.py: runs inside an uncommitted
transaction per test, rolled back at fixture teardown (services never
commit — caller-owns-the-transaction).
"""

import os
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.db.auth import User
from app.db.chat import ChatAttachment
from app.db.enums import (
    ChatThreadStatus,
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
    MAX_MESSAGE_BODY_LENGTH,
    AttachmentAlreadyLinkedError,
    AttachmentNotFoundError,
    AttachmentOwnershipError,
    MessageBodyTooLongError,
    ThreadCompletedError,
    ThreadNotFoundError,
    get_or_create_thread,
    get_thread,
    list_messages,
    list_threads,
    list_threads_with_unread,
    mark_thread_read,
    save_draft,
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

    def test_send_message_raises_once_the_thread_is_completed(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        # Unit 25 (MEADOWOPS-DOM-019, security review, LOW): "the
        # Analyst's most recent message is the submission of record"
        # (PRD 6.6 step 8) - a message sent after Completed would
        # silently outrun the record the evaluation was already graded
        # against.
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        thread.status = ChatThreadStatus.COMPLETED
        session.flush()
        with pytest.raises(ThreadCompletedError):
            send_message(
                session,
                thread_id=thread.id,
                sender_user_id=admin_id,
                sender_role=UserRole.ADMIN,
                body="too late",
            )


class TestSendMessageWithAttachment:
    """Unit 30c (MEADOWOPS-UI-005, S1-FR-15/PRD 347/380, B12 follow-on to
    U30): send_message's attachment-claiming path. Attachments are built
    directly as ChatAttachment rows here (not through app.services.
    chat_attachments.upload_attachment) — this class tests send_message's
    own ownership/claim logic in isolation from upload validation, which
    tests/services/test_chat_attachments.py already covers."""

    def _make_attachment(
        self, session: Session, *, thread_id: uuid.UUID, uploaded_by_user_id: uuid.UUID
    ) -> ChatAttachment:
        attachment = ChatAttachment(
            thread_id=thread_id,
            uploaded_by_user_id=uploaded_by_user_id,
            storage_key=uuid.uuid4().hex,
            original_filename="evidence.jpg",
            content_type="image/jpeg",
            size_bytes=123,
        )
        session.add(attachment)
        session.flush()
        return attachment

    def test_claims_a_valid_attachment(
        self, session: Session, scenario_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        attachment = self._make_attachment(
            session, thread_id=thread.id, uploaded_by_user_id=analyst_id
        )
        message = send_message(
            session,
            thread_id=thread.id,
            sender_user_id=analyst_id,
            sender_role=UserRole.ANALYST,
            body="see attached",
            attachment_id=attachment.id,
        )
        assert message.attachment_ref == str(attachment.id)
        assert attachment.message_id == message.id

    def test_raises_for_an_unknown_attachment_id(
        self, session: Session, scenario_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        with pytest.raises(AttachmentNotFoundError):
            send_message(
                session,
                thread_id=thread.id,
                sender_user_id=analyst_id,
                sender_role=UserRole.ANALYST,
                body="see attached",
                attachment_id=uuid.uuid4(),
            )

    def test_raises_when_the_attachment_belongs_to_a_different_thread(
        self, session: Session, scenario_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        other_thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.IT_MANAGER
        )
        attachment = self._make_attachment(
            session, thread_id=other_thread.id, uploaded_by_user_id=analyst_id
        )
        with pytest.raises(AttachmentOwnershipError):
            send_message(
                session,
                thread_id=thread.id,
                sender_user_id=analyst_id,
                sender_role=UserRole.ANALYST,
                body="see attached",
                attachment_id=attachment.id,
            )

    def test_raises_when_a_builder_tries_to_claim_the_analysts_attachment(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        """The structural half of S1-FR-15's Analyst-side-only scoping
        (see app.services.chat.AttachmentOwnershipError's own docstring):
        an attachment's uploaded_by_user_id is only ever set by the
        require_analyst-gated upload route, so a Builder-sent message can
        never satisfy this ownership check against their own user_id -
        proven directly here, not just asserted by the upload route's own
        role gate."""
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        attachment = self._make_attachment(
            session, thread_id=thread.id, uploaded_by_user_id=analyst_id
        )
        with pytest.raises(AttachmentOwnershipError):
            send_message(
                session,
                thread_id=thread.id,
                sender_user_id=admin_id,
                sender_role=UserRole.ADMIN,
                body="see attached",
                attachment_id=attachment.id,
            )

    def test_raises_when_the_attachment_already_backs_another_message(
        self, session: Session, scenario_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        attachment = self._make_attachment(
            session, thread_id=thread.id, uploaded_by_user_id=analyst_id
        )
        send_message(
            session,
            thread_id=thread.id,
            sender_user_id=analyst_id,
            sender_role=UserRole.ANALYST,
            body="first message with this attachment",
            attachment_id=attachment.id,
        )
        with pytest.raises(AttachmentAlreadyLinkedError):
            send_message(
                session,
                thread_id=thread.id,
                sender_user_id=analyst_id,
                sender_role=UserRole.ANALYST,
                body="second message trying to reuse it",
                attachment_id=attachment.id,
            )

    def test_a_failed_send_leaves_the_attachment_unclaimed(
        self, session: Session, scenario_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        attachment = self._make_attachment(
            session, thread_id=thread.id, uploaded_by_user_id=analyst_id
        )
        with pytest.raises(MessageBodyTooLongError):
            send_message(
                session,
                thread_id=thread.id,
                sender_user_id=analyst_id,
                sender_role=UserRole.ANALYST,
                body="x" * (MAX_MESSAGE_BODY_LENGTH + 1),
                attachment_id=attachment.id,
            )
        assert attachment.message_id is None


class TestSendMessageDeadlineTracking:
    """Unit 30a (MEADOWOPS-UI-003, PRD 6.1, B12): "Response windows: default
    3-5 real-world days per round" - a message from the Builder (persona/
    admin role) starts the Analyst's response window; the Analyst's own
    reply clears it. Catalog row 15 depends on this: no deadline_at, no
    overdue concept to sweep for."""

    def test_a_builder_message_sets_the_deadline_response_window_days_out(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        before = datetime.now(timezone.utc)
        send_message(
            session,
            thread_id=thread.id,
            sender_user_id=admin_id,
            sender_role=UserRole.ADMIN,
            body="VP wants a status update",
            response_window_days=3,
        )
        session.refresh(thread)
        assert thread.deadline_at is not None
        assert before + timedelta(days=3) <= thread.deadline_at

    def test_an_analyst_reply_clears_the_deadline(
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
        assert thread.deadline_at is not None

        send_message(
            session, thread_id=thread.id, sender_user_id=analyst_id,
            sender_role=UserRole.ANALYST, body="Working on it",
        )
        session.refresh(thread)
        assert thread.deadline_at is None

    def test_a_new_message_resets_the_notified_flags(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        """Idempotency pair backing catalog row 30 - a fresh round (new
        deadline_at) is eligible for its own DEADLINE_APPROACHING/
        DEADLINE_MISSED notifications again, not permanently suppressed by
        a prior round's sweep having already fired."""
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        send_message(
            session, thread_id=thread.id, sender_user_id=admin_id,
            sender_role=UserRole.ADMIN, body="VP wants a status update",
        )
        session.refresh(thread)
        thread.deadline_approaching_notified = True
        thread.overdue_notified = True
        session.flush()

        send_message(
            session, thread_id=thread.id, sender_user_id=analyst_id,
            sender_role=UserRole.ANALYST, body="Working on it",
        )
        session.refresh(thread)
        assert thread.deadline_approaching_notified is False
        assert thread.overdue_notified is False


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


class TestDraftPersistence:
    """Unit 30b (MEADOWOPS-UI-004, PRD 6.1 'Drafting' bullet, catalog row
    31, B12 follow-on to U30): a per-(thread, user) draft, backed by
    chat.chat_thread_draft (migration 0025) and surfaced through
    list_threads_with_unread's own draft_body field - see
    ChatThreadDraft's own docstring for why this is a table of its own
    rather than folded into read-state."""

    def _draft_body(self, session: Session, *, thread_id: uuid.UUID, user_id: uuid.UUID) -> str:
        items = list_threads_with_unread(session, user_id=user_id)
        return next(item.draft_body for item in items if item.thread.id == thread_id)

    def test_save_draft_raises_for_an_unknown_thread(
        self, session: Session, admin_id: uuid.UUID
    ) -> None:
        with pytest.raises(ThreadNotFoundError):
            save_draft(session, thread_id=uuid.uuid4(), user_id=admin_id, body="hello")

    def test_a_thread_with_no_saved_draft_has_an_empty_draft_body(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        assert self._draft_body(session, thread_id=thread.id, user_id=admin_id) == ""

    def test_save_draft_then_it_is_readable_back(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        save_draft(session, thread_id=thread.id, user_id=admin_id, body="typing a status update")
        assert (
            self._draft_body(session, thread_id=thread.id, user_id=admin_id)
            == "typing a status update"
        )

    def test_saving_again_overwrites_rather_than_duplicates(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        save_draft(session, thread_id=thread.id, user_id=admin_id, body="first draft")
        save_draft(session, thread_id=thread.id, user_id=admin_id, body="first draft, revised")
        assert (
            self._draft_body(session, thread_id=thread.id, user_id=admin_id)
            == "first draft, revised"
        )

    def test_saving_an_empty_body_clears_a_previously_saved_draft(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        save_draft(session, thread_id=thread.id, user_id=admin_id, body="never mind")
        save_draft(session, thread_id=thread.id, user_id=admin_id, body="")
        assert self._draft_body(session, thread_id=thread.id, user_id=admin_id) == ""

    def test_saving_a_whitespace_only_body_also_clears_it(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        save_draft(session, thread_id=thread.id, user_id=admin_id, body="something")
        save_draft(session, thread_id=thread.id, user_id=admin_id, body="   \n  ")
        assert self._draft_body(session, thread_id=thread.id, user_id=admin_id) == ""

    def test_save_draft_rejects_a_body_over_the_length_cap(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        with pytest.raises(MessageBodyTooLongError):
            save_draft(
                session,
                thread_id=thread.id,
                user_id=admin_id,
                body="x" * (MAX_MESSAGE_BODY_LENGTH + 1),
            )

    def test_a_builders_draft_and_an_analysts_draft_on_the_same_thread_never_collide(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        """The exact collision an advisor review flagged before
        implementation: the Builder's persona-message draft and the
        Analyst's reply draft target the same thread_id. Per-(thread,
        user) storage means neither ever overwrites the other's."""
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        save_draft(session, thread_id=thread.id, user_id=admin_id, body="Builder's persona draft")
        save_draft(session, thread_id=thread.id, user_id=analyst_id, body="Analyst's reply draft")
        assert (
            self._draft_body(session, thread_id=thread.id, user_id=admin_id)
            == "Builder's persona draft"
        )
        assert (
            self._draft_body(session, thread_id=thread.id, user_id=analyst_id)
            == "Analyst's reply draft"
        )

    def test_a_successful_send_clears_only_the_senders_own_draft(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID, analyst_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        save_draft(session, thread_id=thread.id, user_id=admin_id, body="about to send this")
        save_draft(session, thread_id=thread.id, user_id=analyst_id, body="Analyst's own, untouched")

        send_message(
            session, thread_id=thread.id, sender_user_id=admin_id,
            sender_role=UserRole.ADMIN, body="about to send this",
        )

        assert self._draft_body(session, thread_id=thread.id, user_id=admin_id) == ""
        assert (
            self._draft_body(session, thread_id=thread.id, user_id=analyst_id)
            == "Analyst's own, untouched"
        )

    def test_a_failed_send_leaves_the_draft_untouched(
        self, session: Session, scenario_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        thread.status = ChatThreadStatus.COMPLETED
        session.flush()
        save_draft(session, thread_id=thread.id, user_id=admin_id, body="stuck in the composer")

        with pytest.raises(ThreadCompletedError):
            send_message(
                session, thread_id=thread.id, sender_user_id=admin_id,
                sender_role=UserRole.ADMIN, body="too late",
            )

        assert (
            self._draft_body(session, thread_id=thread.id, user_id=admin_id)
            == "stuck in the composer"
        )
