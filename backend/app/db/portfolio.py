"""Unit 26 (MEADOWOPS-DOM-020, business id MEADOWOPS-DOMAIN-015, PRD 6.10):
storage for the Analyst's own seven-question written reflection on one
completed scenario - the one piece of PRD 6.10's compiled portfolio
artifact that isn't already derivable from existing tables.

`engine.portfolio_artifact` deliberately does NOT snapshot the scenario's
trigger, chat responses/pushback rounds, draft evaluation, or reviewer
notes named alongside the reflection in PRD 6.10's own text - every one of
those already lives in `engine.scenario`/`chat.chat_message`/
`engine.evaluation`/`engine.human_review` and re-storing them here would be
a second, driftable copy of data this codebase already treats as the
single source of truth (same DRY reasoning app.services.evaluation's own
docstring gives for `outcome` sourcing from `Scenario.ground_truth` rather
than a duplicate field). app.services.portfolio.get_portfolio_export
compiles the full artifact on demand instead - see that module.

Table named `portfolio_artifact`, matching Appendix B's data-dictionary
entry exactly, even though this row only holds the analyst-authored half
of what PRD 6.10 calls "the artifact" - the compiled document, not this
table, is the artifact PRD 6.10 actually describes.

Immutability (BEFORE UPDATE/DELETE/TRUNCATE trigger, migration 0021): a
submitted reflection is a permanent record of what the Analyst actually
thought at the time, the same reasoning ChatMessage/Evaluation/HumanReview
already apply - allowing a later edit would let the "what I initially
thought" answer quietly become "what I now know", defeating the point of
capturing it.

`submitted_by_user_id` (security review of this unit) is a non-nullable FK
to `live.user.id` recording who authored the reflection - the write route
is reject_service_role, not require_admin, so this can be either the
Analyst or the Builder, and was previously unrecorded.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base

_ENGINE_SCHEMA = "engine"


class PortfolioArtifact(Base):
    __tablename__ = "portfolio_artifact"
    __table_args__ = {"schema": _ENGINE_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    # Hard FK, unique - one reflection per ChatThread (PRD 6.10: "compiled
    # per scenario", and DD-25 already established one thread per
    # (scenario, persona); a scenario's single thread is what step 8's
    # Final submission actually completes).
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat.chat_thread.id"),
        nullable=False,
        unique=True,
    )
    # Security review of this unit: who authored the reflection - either
    # role, since this route is reject_service_role. See module docstring.
    submitted_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live.user.id"), nullable=False
    )
    # PRD 6.10's seven-question reflection, verbatim order: what happened,
    # what I initially thought, what evidence mattered, what I missed,
    # what changed after pushback, what I'd do differently, what skill
    # improved.
    reflection_what_happened: Mapped[str] = mapped_column(Text, nullable=False)
    reflection_initial_thought: Mapped[str] = mapped_column(Text, nullable=False)
    reflection_evidence_that_mattered: Mapped[str] = mapped_column(Text, nullable=False)
    reflection_what_missed: Mapped[str] = mapped_column(Text, nullable=False)
    reflection_what_changed_after_pushback: Mapped[str] = mapped_column(Text, nullable=False)
    reflection_what_differently: Mapped[str] = mapped_column(Text, nullable=False)
    reflection_skill_improved: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
