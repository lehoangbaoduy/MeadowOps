"""Unit 21a (MEADOWOPS-DOM-014, PRD 6.13, §7, Appendix B): the persistent
substrate for the Builder<->Analyst persona chat — one persistent
ChatThread per (Scenario, persona) pair (DD-25), and its immutable
ChatMessage rows.

Lives in a new `chat` schema (migration 0018), not `live` or `engine` —
this is PRD §7's one other named exception to the no-direct-cross-subsystem
-access rule (after the Query Playground's sandbox schema): a single store
both subsystems' own API layer reads and writes, never a subsystem reaching
into the other's schema directly. `chat`'s own service/domain modules are
intentionally NOT routed through `app.services.subsystem2`'s HTTP-only
boundary (app.domain.subsystem_boundary) — that boundary polices Subsystem
2 code reaching Subsystem 1's *own* `live` data, the same way it already
exempts `app.db.scenario` (Subsystem 2's own `engine` data); chat is a
third, shared category, not `live`, so the exemption applies here too
(pre-implementation security review of this unit, considered and
deliberately not adding `app.db.chat` to FORBIDDEN_MODULES).

No `app.db.chat.Interaction` model exists here on purpose — grepped the
codebase before writing this migration and confirmed no prior unit ever
built one (only migrations up to 0017 existed), so Appendix B's "Interaction
rows... now correspond to its thread's Chat Messages rather than a separate
parallel record" is satisfied by never building the parallel record at all.

Immutability (PRD 6.13/ER-6) is enforced by a database trigger, not just the
absence of an UPDATE/DELETE route — see migration 0018's own docstring for
why a plain REVOKE can't work here (the app's own DB connection is the
schema-owning role, and owners bypass grants).
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base, pg_enum
from app.db.enums import ChatThreadStatus, NotificationKind, StakeholderPersona, UserRole

_CHAT_SCHEMA = "chat"


class ChatThread(Base):
    __tablename__ = "chat_thread"
    __table_args__ = (
        UniqueConstraint(
            "scenario_id", "persona", name="ux_chat_thread_scenario_persona"
        ),
        {"schema": _CHAT_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    # Hard FK, unlike Scenario.source_exception_flag_id's soft reference
    # (app/db/scenario.py's own docstring) — a thread has no meaning at all
    # without the scenario it belongs to, and engine.scenario rows are never
    # deleted (only status-transitioned), so there's no analogous
    # auto-resolve/reconcile churn to worry about here.
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engine.scenario.id"), nullable=False
    )
    persona: Mapped[StakeholderPersona] = mapped_column(
        pg_enum(StakeholderPersona, "stakeholder_persona", schema=_CHAT_SCHEMA),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Unit 25 (MEADOWOPS-DOM-019, PRD 6.6 step 8) - see ChatThreadStatus's
    # own docstring for why this is two states, not PRD 6.1's full nine.
    status: Mapped[ChatThreadStatus] = mapped_column(
        pg_enum(ChatThreadStatus, "chat_thread_status", schema=_CHAT_SCHEMA),
        nullable=False,
        server_default=text("'open'"),
    )
    # Unit 30a (MEADOWOPS-UI-003, PRD 6.1, B12): "Response windows: default
    # 3-5 real-world days per round" - set by app.services.chat.send_message
    # to now + response_window_days whenever the Builder (persona/admin
    # role) sends a message, since that starts the Analyst's response
    # window; cleared back to null whenever the Analyst replies. Null for a
    # thread with no message yet or whose most recent sender was the
    # Analyst - "approaching"/"overdue" (catalog row 15) is a derived
    # condition over this column plus wall-clock now(), not a persisted
    # ChatThreadStatus member (see that enum's own docstring for why).
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Idempotency pair backing catalog row 30's "no double-fires" - each is
    # true once app.services.notifications.sweep_thread_deadlines has
    # already written the corresponding Notification for the *current*
    # deadline_at, and both reset to false every time deadline_at is set or
    # cleared (a fresh round is a fresh deadline, eligible for its own
    # notifications again). A sweep re-run after a scheduler restart is
    # therefore a no-op for a thread already flagged, rather than a second
    # notification row.
    deadline_approaching_notified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    overdue_notified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )


class ChatMessage(Base):
    __tablename__ = "chat_message"
    __table_args__ = {"schema": _CHAT_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{_CHAT_SCHEMA}.chat_thread.id"), nullable=False
    )
    # Both the accountable identity (FK, audit trail — same convention as
    # QueryLog.user_id) and the denormalized role (cheap to read for every
    # message-list render without a join to live.user — set once at INSERT,
    # never touched again, so there's no drift risk an immutable row can
    # develop). Derived server-side from the caller's verified session in
    # every case (app.api.chat) — never accepted from the request body,
    # closing the class of forgery bug Unit 20a's pre-implementation review
    # caught (client-side role trust).
    sender_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live.user.id"), nullable=False
    )
    sender_role: Mapped[UserRole] = mapped_column(
        pg_enum(UserRole, "user_role", schema="live"), nullable=False
    )
    # Bounded — code review precedent: LoginRequest's own docstring on why
    # an unbounded field fed into shared infrastructure (there, a rate
    # limiter's dict key; here, a frame this unit's ConnectionRegistry
    # broadcasts to every live connection) needs an explicit cap, not just
    # "the database can hold a lot of text."
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Nullable placeholder (Appendix B names this column, not the storage
    # infrastructure behind it) — file attachment upload/storage/serving is
    # explicitly out of scope for this unit; PRD 8.4 calls attachments the
    # largest new attack surface the chat feature introduces, deliberately
    # not taken on as a drive-by inside the delivery-substrate unit.
    attachment_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ChatThreadReadState(Base):
    """Unit 21 (MEADOWOPS-DOM-015, S1-FR-15): per-(thread, user) "last read"
    marker backing unread-thread badges. Deliberately a separate, ordinary
    mutable table (migration 0019) rather than a column on ChatMessage —
    that table is immutability-trigger-protected and read-state is by
    definition something that changes on every read, the opposite of what
    that trigger exists to prevent. No `created_at`/id — the natural key
    *is* the (thread_id, user_id) pair, upserted on every mark-read call."""

    __tablename__ = "chat_thread_read_state"
    __table_args__ = {"schema": _CHAT_SCHEMA}

    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{_CHAT_SCHEMA}.chat_thread.id"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live.user.id"), primary_key=True
    )
    last_read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class Notification(Base):
    """Unit 30a (MEADOWOPS-UI-003, PRD 6.1, B12 follow-on to U30): a
    durable delivery record, not part of the chat evidentiary trail - no
    ER-6 immutability trigger here (unlike ChatMessage/engine.evaluation),
    since `read_at` is by definition something that changes after the row
    is written, the same reasoning ChatThreadReadState's own docstring
    already gives for staying an ordinary mutable table.

    Written only by app.services.notifications.sweep_thread_deadlines
    today (see NotificationKind's own docstring for why only two of PRD
    6.1's four named kinds are modeled here). Persisted as real rows
    (rather than only ever pushed live over the chat websocket) is what
    makes catalog row 30's "pending notifications recover cleanly ... no
    lost events" provable - a row written before a scheduler restart is
    still there, unread, after it."""

    __tablename__ = "notification"
    __table_args__ = {"schema": _CHAT_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live.user.id"), nullable=False
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{_CHAT_SCHEMA}.chat_thread.id"), nullable=False
    )
    kind: Mapped[NotificationKind] = mapped_column(
        pg_enum(NotificationKind, "notification_kind", schema=_CHAT_SCHEMA), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChatThreadDraft(Base):
    """Unit 30b (MEADOWOPS-UI-004, PRD 6.1 'Drafting' bullet, catalog row
    31, B12 follow-on to U30): per-(thread, user) not-yet-sent composer
    text. Same shape and same reasoning as ChatThreadReadState's own
    docstring above - an ordinary mutable table, not a column on the
    immutability-trigger-protected ChatMessage, and a table of its own
    rather than folded into ChatThreadReadState itself: read-state and
    draft text are two unrelated concerns that only happen to share a
    natural key, the same distinction that already separated read-state
    from ChatMessage in the first place.

    A row here means "this user has unsent text on this thread" - deleted
    (not written empty) once that stops being true, either because
    app.services.chat.send_message clears it on a successful send, or
    because app.services.chat.save_draft is called with an empty body.
    No `created_at` for the same reason ChatThreadReadState has none: the
    natural key *is* the (thread_id, user_id) pair, upserted on every
    save-draft call."""

    __tablename__ = "chat_thread_draft"
    __table_args__ = {"schema": _CHAT_SCHEMA}

    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{_CHAT_SCHEMA}.chat_thread.id"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live.user.id"), primary_key=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ChatAttachment(Base):
    """Unit 30c (MEADOWOPS-UI-005, S1-FR-15/PRD 347/380, B12 follow-on to
    U30): metadata for an Analyst-uploaded file (PRD 8.4: images, PDF, CSV
    only, hard size cap, object storage not this database - see migration
    0026's own docstring for the full rationale, including why `message_id`
    is nullable+unique rather than set at row creation).

    A row with `message_id IS NULL` is an uploaded-but-not-yet-sent
    attachment - the two-phase flow this table exists for. Never deleted on
    its own; an unclaimed row left behind by a send that never completed
    (e.g. the client uploaded, then abandoned the compose) is an accepted,
    documented known limitation at this project's scale, not actively swept
    - same precedent as B13's other single-writer, not-race-safe app-level
    guards."""

    __tablename__ = "chat_attachment"
    __table_args__ = {"schema": _CHAT_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{_CHAT_SCHEMA}.chat_thread.id"), nullable=False
    )
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live.user.id"), nullable=False
    )
    # Unique (not just indexed): the DB-level half of "an attachment can back
    # at most one message" - see this class's own docstring above.
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{_CHAT_SCHEMA}.chat_message.id"),
        nullable=True,
        unique=True,
    )
    # Opaque token (uuid4().hex, generated server-side - app.services.
    # chat_attachments) used as the object-store key. Never derived from
    # original_filename or any other user-controlled value, so there is no
    # path-traversal surface even though LocalFilesystemAttachmentStorage
    # joins it directly onto a base directory.
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    # Stored for the Content-Disposition response header only - never used
    # to pick a storage path or to decide the trusted content type (that's
    # sniffed from bytes, see app.domain.attachment_validation).
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    # The sniffed, trusted content type (never the client-declared one) -
    # see app.domain.attachment_validation.validate_attachment_content.
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
