import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, pg_enum
from app.db.enums import (
    CompetencyCluster,
    DifficultyTier,
    ScenarioSource,
    ScenarioStatus,
    ScenarioType,
)


class Scenario(Base, TimestampMixin):
    """Unit 18 (MEADOWOPS-DOM-011, business id MEADOWOPS-DOMAIN-009, PRD
    6.4): Builder-authored work scenario. Lives in the `engine` schema
    (provisioned since Migration 0001 specifically for "scenario,
    evaluation, portfolio", never used until now — DD-24 point 1), not
    `live`, following the same schema-override-on-shared-Base pattern
    Unit 17's `reporting.*` tables established.

    `source_exception_flag_id` is a soft reference, not a hard FK (DD-24
    point 6, same reasoning already applied to
    app.db.ledger.DecisionEvent.scenario_id): the ExceptionFlag it points
    at can later auto-resolve or be reconciled by
    app.services.exception_engine's scheduler, so this column is
    provenance/audit trail only — every fact this scenario actually needs
    is snapshotted into `ground_truth` at creation time
    (app.domain.scenario.build_ground_truth_from_exception_flag), never
    re-read live from the flag after that point.

    No Analyst read path anywhere reaches this table (DD-24 point 4): every
    route in app.api.admin_scenarios is require_admin-only, unlike every
    other Subsystem-1-facing resource in this codebase. An undelivered
    scenario visible early would spoil it before the Analyst ever receives
    it — delivery infrastructure (ChatThread/ChatMessage) doesn't exist
    until U21/U21a.
    """

    __tablename__ = "scenario"
    __table_args__ = {"schema": "engine"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    scenario_type: Mapped[ScenarioType] = mapped_column(
        pg_enum(ScenarioType, "scenario_type", schema="engine"), nullable=False
    )
    competency_cluster: Mapped[CompetencyCluster] = mapped_column(
        pg_enum(CompetencyCluster, "competency_cluster", schema="engine"), nullable=False
    )
    difficulty_tier: Mapped[DifficultyTier] = mapped_column(
        pg_enum(DifficultyTier, "difficulty_tier", schema="engine"), nullable=False
    )
    source: Mapped[ScenarioSource] = mapped_column(
        pg_enum(ScenarioSource, "scenario_source", schema="engine"), nullable=False
    )
    # Soft reference — see class docstring. No ForeignKey() on purpose.
    source_exception_flag_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # Soft reference (migration 0023, PRD 4.2 line 130) — same reasoning as
    # source_exception_flag_id above: world_state rows are append-only, so a
    # plain UUID pin is enough to survive any number of later resets
    # (PRD 9.2 catalog row 7).
    world_state_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    ground_truth: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[ScenarioStatus] = mapped_column(
        pg_enum(ScenarioStatus, "scenario_status", schema="engine"),
        nullable=False,
        server_default=text("'draft'"),
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live.user.id"), nullable=False
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
