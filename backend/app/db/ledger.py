import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, pg_enum
from app.domain.ledger import DecisionEventStatus


class RecordType(str, enum.Enum):
    """PRD 4.4: every ledger row is either an operational event or a
    decision. Only decisions carry the full lifecycle in `status`."""

    OPERATIONAL_EVENT = "operational_event"
    DECISION = "decision"


class ApprovalAuthority(str, enum.Enum):
    MANAGER = "manager"
    PROCUREMENT_OPERATIONS = "procurement_operations"
    INFORMATIONAL_ONLY = "informational_only"


class DecisionOutcome(str, enum.Enum):
    SUCCEEDED = "succeeded"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    FAILED = "failed"
    UNINTENDED_CONSEQUENCE = "unintended_consequence"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class EntityType(str, enum.Enum):
    """The small known set of master-data kinds a ledger row can concern
    (PRD 5.2). `entity_id` stays a free string (its format varies by which
    of these it is), but the *kind* itself doesn't need to be — security
    review of this unit: an enum here closes off typos ('suplier') at the
    type level, at negligible cost, matching the pattern already used for
    every other categorical column on this table."""

    SUPPLIER = "supplier"
    WAREHOUSE = "warehouse"
    PRODUCT = "product"
    CUSTOMER = "customer"
    CARRIER = "carrier"


class DecisionEvent(Base):
    __tablename__ = "decision_event"
    __table_args__ = (
        CheckConstraint("id != supersedes_id", name="ck_decision_event_no_self_supersede"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    record_type: Mapped[RecordType] = mapped_column(
        pg_enum(RecordType, "record_type"), nullable=False
    )
    status: Mapped[DecisionEventStatus] = mapped_column(
        pg_enum(DecisionEventStatus, "decision_event_status"), nullable=False
    )

    # Deliberately not a hard FK: Subsystem 2's Scenario table doesn't exist
    # yet (built much later, Phase 3) and — separately — a scenario_id must
    # keep referencing a completed scenario even if scenario retention
    # policy ever prunes old rows. Tightened once Scenario exists if the
    # team decides a real FK adds value at that point.
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # entity_id is deliberately not a hard FK to e.g. live.supplier.id: its
    # target table varies per row so a single FK can't point at the right
    # one anyway, and master data is soft-deleted (is_active), never
    # hard-deleted, so this never orphans in practice (PRD 9.2 row 12 —
    # callback scenarios must survive a deactivated entity). entity_type
    # itself is a closed, known set (PRD 5.2), so it *is* an enum.
    entity_type: Mapped[EntityType] = mapped_column(
        pg_enum(EntityType, "ledger_entity_type"), nullable=False
    )
    entity_id: Mapped[str] = mapped_column(String, nullable=False)

    title: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approval_authority: Mapped[ApprovalAuthority | None] = mapped_column(
        pg_enum(ApprovalAuthority, "approval_authority"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String, nullable=True)
    implemented_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    outcome: Mapped[DecisionOutcome | None] = mapped_column(
        pg_enum(DecisionOutcome, "decision_outcome"), nullable=True
    )
    outcome_recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    outcome_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    stale_flagged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live.decision_event.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
