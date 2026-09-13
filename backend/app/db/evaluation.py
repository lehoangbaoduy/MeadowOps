"""Unit 25 (MEADOWOPS-DOM-019, business id MEADOWOPS-DOMAIN-014, PRD 6.6
steps 8-9, 6.8): the AI evaluation framework's storage. Lives in the
`engine` schema (provisioned since Migration 0001 specifically for
"scenario, evaluation, portfolio" - U18's own docstring), sibling to
Scenario, not `chat` - unlike ChatThread/ChatMessage this is Subsystem 2's
own protected data (ER-5: hidden from the Analyst during normal use), not a
store both subsystems' API layer reads and writes.

Immutability (ER-6, "historical evaluation records never silently
rewritten") is enforced the same way as chat.chat_message (migration 0018's
own docstring has the full reasoning for why a trigger, not a plain
REVOKE) - migration 0020 adds the identical BEFORE UPDATE/DELETE/TRUNCATE
trigger shape here.

No status column - every row is implicitly DRAFT/NOT AUTHORITATIVE (ER-1);
no other value exists until U26's Human Review table attaches an
authoritative verdict to a row here without ever mutating the row itself.

No TimestampMixin (unlike Scenario) - that mixin's `updated_at` with
`onupdate=func.now()` would be actively misleading on a row the database
itself refuses to ever UPDATE; `created_at` alone, defined the same way
ChatThread/ChatMessage already define theirs.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base, pg_enum
from app.db.enums import DifficultyRecommendation

_ENGINE_SCHEMA = "engine"


class Evaluation(Base):
    __tablename__ = "evaluation"
    __table_args__ = {"schema": _ENGINE_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    # Hard FK, unique - one Evaluation per ChatThread (PRD 6.6: "final
    # submission" (step 8) then "Draft AI evaluation" (step 9) is a single
    # per-thread transition, not a repeatable action). Unique, not just
    # indexed, so a concurrent double-call to complete_thread_and_generate_
    # evaluation can't insert two rows for the same thread even under a
    # race - the calling route also checks ChatThread.status first, this is
    # the DB-level backstop.
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat.chat_thread.id"),
        nullable=False,
        unique=True,
    )
    # e.g. "draft_evaluation/v1" (PromptTemplate.name + "/" + .version) -
    # ER-6 traceability: which frozen template version produced this row,
    # since EVALUATION_TEMPLATE itself may gain a v2 someday without this
    # row's own content ever changing.
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    strengths: Mapped[str] = mapped_column(Text, nullable=False)
    gaps: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    senior_analyst_pushback: Mapped[str] = mapped_column(Text, nullable=False)
    final_verdict: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_next_skill_focus: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty_recommendation: Mapped[DifficultyRecommendation] = mapped_column(
        pg_enum(DifficultyRecommendation, "difficulty_recommendation", schema=_ENGINE_SCHEMA),
        nullable=False,
    )
    # Full raw AI response text, for audit/debugging - not surfaced on any
    # route today, kept the same "raw content alongside the parsed fields"
    # discipline this project already applies wherever it schema-validates
    # a Claude response (e.g. app.db.ledger's own rationale field shape).
    raw_response: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
