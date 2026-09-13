"""Unit 30c (MEADOWOPS-UI-005, S1-FR-15/PRD 347/380, B12 follow-on to U30):
app.services.chat_attachments — upload validation/storage/persistence, and
the message-to-attachment read path. Same non-autocommit-transaction-per-
test discipline as tests/services/test_chat_service.py.

Storage is a fake, in-memory double (never the real filesystem) - this
module's own contract is "storage is always an explicit parameter" (see
app.services.chat_attachments's own docstring) specifically so tests never
need real I/O.
"""

import os
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.core.storage import AttachmentStorage
from app.db.auth import User
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
from app.domain.attachment_validation import UnsupportedAttachmentTypeError
from app.services.baseline_data import seed_master_data
from app.services.chat import ThreadCompletedError, ThreadNotFoundError, get_or_create_thread
from app.services.chat_attachments import (
    AttachmentRecordMissingError,
    AttachmentTooLargeError,
    get_attachment_for_message,
    upload_attachment,
)
from app.services.exception_rule_defaults import seed_exception_rule_thresholds
from app.services.scenario_service import create_scenario_from_exception_flag

_PRODUCT_ID = "SKU-COR-001"
_WAREHOUSE_ID = "WH-EAST"
_ANALYST_EMAIL = "zztest-chat-attach-analyst@meadowops.local"
_ADMIN_EMAIL = "zztest-chat-attach-admin@meadowops.local"

_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00rest-of-a-fake-jpeg"


class FakeAttachmentStorage(AttachmentStorage):
    def __init__(self) -> None:
        self.saved: dict[str, bytes] = {}

    def save(self, key: str, content: bytes) -> None:
        self.saved[key] = content

    def load(self, key: str) -> bytes:
        return self.saved[key]

    def delete(self, key: str) -> None:
        self.saved.pop(key, None)


@pytest.fixture
def storage() -> FakeAttachmentStorage:
    return FakeAttachmentStorage()


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
        title="zztest chat attachment scenario",
        created_by=admin_id,
    )
    return scenario.id


@pytest.fixture
def thread_id(session: Session, scenario_id: uuid.UUID) -> uuid.UUID:
    thread = get_or_create_thread(session, scenario_id=scenario_id, persona=StakeholderPersona.CFO)
    return thread.id


class TestUploadAttachment:
    def test_uploads_a_valid_jpeg_and_returns_its_metadata(
        self,
        session: Session,
        storage: FakeAttachmentStorage,
        thread_id: uuid.UUID,
        analyst_id: uuid.UUID,
    ) -> None:
        attachment = upload_attachment(
            session,
            storage,
            thread_id=thread_id,
            uploaded_by_user_id=analyst_id,
            original_filename="evidence.jpg",
            claimed_content_type="image/jpeg",
            content=_JPEG_BYTES,
            max_size_bytes=5_000_000,
        )
        assert attachment.id is not None
        assert attachment.thread_id == thread_id
        assert attachment.uploaded_by_user_id == analyst_id
        assert attachment.original_filename == "evidence.jpg"
        assert attachment.content_type == "image/jpeg"
        assert attachment.size_bytes == len(_JPEG_BYTES)
        assert attachment.message_id is None

    def test_writes_the_content_to_storage_under_an_opaque_key(
        self,
        session: Session,
        storage: FakeAttachmentStorage,
        thread_id: uuid.UUID,
        analyst_id: uuid.UUID,
    ) -> None:
        attachment = upload_attachment(
            session,
            storage,
            thread_id=thread_id,
            uploaded_by_user_id=analyst_id,
            original_filename="evidence.jpg",
            claimed_content_type="image/jpeg",
            content=_JPEG_BYTES,
            max_size_bytes=5_000_000,
        )
        assert storage.load(attachment.storage_key) == _JPEG_BYTES
        # Opaque - never derived from the user-supplied filename.
        assert attachment.storage_key != "evidence.jpg"

    def test_rejects_a_file_over_the_size_cap(
        self,
        session: Session,
        storage: FakeAttachmentStorage,
        thread_id: uuid.UUID,
        analyst_id: uuid.UUID,
    ) -> None:
        with pytest.raises(AttachmentTooLargeError):
            upload_attachment(
                session,
                storage,
                thread_id=thread_id,
                uploaded_by_user_id=analyst_id,
                original_filename="huge.jpg",
                claimed_content_type="image/jpeg",
                content=_JPEG_BYTES,
                max_size_bytes=len(_JPEG_BYTES) - 1,
            )

    def test_a_too_large_upload_never_touches_storage(
        self,
        session: Session,
        storage: FakeAttachmentStorage,
        thread_id: uuid.UUID,
        analyst_id: uuid.UUID,
    ) -> None:
        with pytest.raises(AttachmentTooLargeError):
            upload_attachment(
                session,
                storage,
                thread_id=thread_id,
                uploaded_by_user_id=analyst_id,
                original_filename="huge.jpg",
                claimed_content_type="image/jpeg",
                content=_JPEG_BYTES,
                max_size_bytes=len(_JPEG_BYTES) - 1,
            )
        assert storage.saved == {}

    def test_rejects_an_unsupported_content_type(
        self,
        session: Session,
        storage: FakeAttachmentStorage,
        thread_id: uuid.UUID,
        analyst_id: uuid.UUID,
    ) -> None:
        with pytest.raises(UnsupportedAttachmentTypeError):
            upload_attachment(
                session,
                storage,
                thread_id=thread_id,
                uploaded_by_user_id=analyst_id,
                original_filename="not-really.csv",
                claimed_content_type="text/csv",
                content=b"<html><body>not a spreadsheet</body></html>",
                max_size_bytes=5_000_000,
            )

    def test_a_rejected_content_type_never_touches_storage(
        self,
        session: Session,
        storage: FakeAttachmentStorage,
        thread_id: uuid.UUID,
        analyst_id: uuid.UUID,
    ) -> None:
        with pytest.raises(UnsupportedAttachmentTypeError):
            upload_attachment(
                session,
                storage,
                thread_id=thread_id,
                uploaded_by_user_id=analyst_id,
                original_filename="not-really.csv",
                claimed_content_type="text/csv",
                content=b"<html><body>not a spreadsheet</body></html>",
                max_size_bytes=5_000_000,
            )
        assert storage.saved == {}

    def test_raises_for_an_unknown_thread(
        self, session: Session, storage: FakeAttachmentStorage, analyst_id: uuid.UUID
    ) -> None:
        with pytest.raises(ThreadNotFoundError):
            upload_attachment(
                session,
                storage,
                thread_id=uuid.uuid4(),
                uploaded_by_user_id=analyst_id,
                original_filename="evidence.jpg",
                claimed_content_type="image/jpeg",
                content=_JPEG_BYTES,
                max_size_bytes=5_000_000,
            )

    def test_raises_once_the_thread_is_completed(
        self,
        session: Session,
        storage: FakeAttachmentStorage,
        scenario_id: uuid.UUID,
        analyst_id: uuid.UUID,
    ) -> None:
        thread = get_or_create_thread(
            session, scenario_id=scenario_id, persona=StakeholderPersona.CFO
        )
        thread.status = ChatThreadStatus.COMPLETED
        session.flush()
        with pytest.raises(ThreadCompletedError):
            upload_attachment(
                session,
                storage,
                thread_id=thread.id,
                uploaded_by_user_id=analyst_id,
                original_filename="evidence.jpg",
                claimed_content_type="image/jpeg",
                content=_JPEG_BYTES,
                max_size_bytes=5_000_000,
            )


class TestGetAttachmentForMessage:
    def test_returns_none_when_the_message_does_not_exist(self, session: Session) -> None:
        assert get_attachment_for_message(session, uuid.uuid4()) is None

    def test_returns_none_when_the_message_has_no_attachment(
        self, session: Session, thread_id: uuid.UUID, admin_id: uuid.UUID
    ) -> None:
        from app.services.chat import send_message

        message = send_message(
            session,
            thread_id=thread_id,
            sender_user_id=admin_id,
            sender_role=UserRole.ADMIN,
            body="no attachment here",
        )
        assert get_attachment_for_message(session, message.id) is None

    def test_returns_the_attachment_a_message_was_sent_with(
        self,
        session: Session,
        storage: FakeAttachmentStorage,
        thread_id: uuid.UUID,
        analyst_id: uuid.UUID,
    ) -> None:
        from app.services.chat import send_message

        attachment = upload_attachment(
            session,
            storage,
            thread_id=thread_id,
            uploaded_by_user_id=analyst_id,
            original_filename="evidence.jpg",
            claimed_content_type="image/jpeg",
            content=_JPEG_BYTES,
            max_size_bytes=5_000_000,
        )
        message = send_message(
            session,
            thread_id=thread_id,
            sender_user_id=analyst_id,
            sender_role=UserRole.ANALYST,
            body="see attached",
            attachment_id=attachment.id,
        )
        found = get_attachment_for_message(session, message.id)
        assert found is not None
        assert found.id == attachment.id
        assert found.message_id == message.id

    def test_raises_when_the_attachment_no_longer_points_back_to_this_message(
        self,
        session: Session,
        storage: FakeAttachmentStorage,
        thread_id: uuid.UUID,
        admin_id: uuid.UUID,
        analyst_id: uuid.UUID,
    ) -> None:
        """Security review (this unit): the should-never-happen state the
        attachment.message_id == message_id check guards against -
        attachment_ref still names this attachment, but the attachment's
        own message_id has since diverged to point at a different message
        (e.g. a future code path that ever set attachment_ref without going
        through send_message's with_for_update claim step). Simulated
        directly against a second, real message (an FK on message_id
        requires one to exist) rather than raced, since the claim lock now
        makes this genuinely unreachable through normal use."""
        from app.services.chat import send_message

        attachment = upload_attachment(
            session,
            storage,
            thread_id=thread_id,
            uploaded_by_user_id=analyst_id,
            original_filename="evidence.jpg",
            claimed_content_type="image/jpeg",
            content=_JPEG_BYTES,
            max_size_bytes=5_000_000,
        )
        message = send_message(
            session,
            thread_id=thread_id,
            sender_user_id=analyst_id,
            sender_role=UserRole.ANALYST,
            body="see attached",
            attachment_id=attachment.id,
        )
        other_message = send_message(
            session,
            thread_id=thread_id,
            sender_user_id=admin_id,
            sender_role=UserRole.ADMIN,
            body="unrelated message",
        )
        attachment.message_id = other_message.id
        session.flush()

        with pytest.raises(AttachmentRecordMissingError):
            get_attachment_for_message(session, message.id)
