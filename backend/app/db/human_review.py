"""Unit 26 (MEADOWOPS-DOM-020, business id MEADOWOPS-DOMAIN-015, PRD 6.6
step 11, ER-1 through ER-6): storage for a monthly reviewer's verdict on
one Evaluation row's difficulty-tier recommendation.

`engine.human_review` is a sibling of `engine.evaluation`, not a column on
it - app.db.evaluation's own docstring names this exact shape: "no other
value exists until U26's Human Review table attaches an authoritative
verdict to a row here without ever mutating the row itself" (ER-1: the AI
evaluation stays labeled DRAFT/NOT AUTHORITATIVE forever; the authoritative
call lives here instead).

`reviewer_name` is free text, not a FK to `live.user` - PRD 14's own Open
Items list the External Human Reviewer as "sourced independently by the
Builder... fully decoupled from Done", so no reviewer account/login exists
in this phase (unlike Admin/Analyst, PRD 5.1). The Builder stands in to
exercise this mechanism structurally, the same role QA test-analyst runs
already have her play elsewhere (PRD 9.1).

`submitted_by_user_id` (security review of this unit) is a separate,
non-nullable FK to `live.user.id` - it records which authenticated account
operated this route (always the Builder in this phase, since the route is
require_admin), not who the external reviewer was. `reviewer_name` and
`submitted_by_user_id` answer different questions and are kept as two
columns rather than collapsed into one.

Immutability (BEFORE UPDATE/DELETE/TRUNCATE trigger, migration 0021) is a
deliberate scope decision, not copied by default: ER-6's own text only
names "historical evaluation records", but ER-3 frames a reviewer
disagreement as a permanent "learning artifact", the same durability
Evaluation/ChatMessage already have - a reviewer verdict silently
rewritten later would undermine that record the same way an edited chat
message would.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base, pg_enum
from app.db.enums import DifficultyRecommendation, HumanReviewVerdict

_ENGINE_SCHEMA = "engine"


class HumanReview(Base):
    __tablename__ = "human_review"
    __table_args__ = (
        # Mirrors the Pydantic model_validator in app.schemas.human_review
        # (defense in depth, same discipline as MAX_MESSAGE_BODY_LENGTH's
        # schema+service pairing) - a direct INSERT that bypasses the
        # service layer entirely still can't desynchronize verdict from
        # overridden_recommendation.
        CheckConstraint(
            "(verdict = 'agree' AND overridden_recommendation IS NULL) OR "
            "(verdict = 'override' AND overridden_recommendation IS NOT NULL)",
            name="ck_human_review_verdict_recommendation_pairing",
        ),
        {"schema": _ENGINE_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    # Hard FK, unique - one Human Review per Evaluation (PRD 6.6 step 11:
    # the monthly reviewer records a single verdict per sampled
    # evaluation, not a repeatable action).
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{_ENGINE_SCHEMA}.evaluation.id"),
        nullable=False,
        unique=True,
    )
    # Security review of this unit: the operator, not the external
    # reviewer - see module docstring for how this differs from
    # reviewer_name below.
    submitted_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live.user.id"), nullable=False
    )
    reviewer_name: Mapped[str] = mapped_column(Text, nullable=False)
    verdict: Mapped[HumanReviewVerdict] = mapped_column(
        pg_enum(HumanReviewVerdict, "human_review_verdict", schema=_ENGINE_SCHEMA),
        nullable=False,
    )
    # ER-4: "reviewer explicitly assesses whether the current tier matches
    # demonstrated level" - required on every row regardless of verdict,
    # not only on an override.
    tier_assessment_notes: Mapped[str] = mapped_column(Text, nullable=False)
    overridden_recommendation: Mapped[DifficultyRecommendation | None] = mapped_column(
        pg_enum(DifficultyRecommendation, "difficulty_recommendation", schema=_ENGINE_SCHEMA),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
