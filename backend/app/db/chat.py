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

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base, pg_enum
from app.db.enums import StakeholderPersona, UserRole

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
