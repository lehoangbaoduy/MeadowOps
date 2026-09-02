import enum
import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, pg_enum
from app.domain.simulation_clock import ClockStatus


class WorldStateKind(str, enum.Enum):
    CLEAN_BASELINE = "clean_baseline"
    INJECTED_STATE = "injected_state"
    SNAPSHOT = "snapshot"
    RESET = "reset"
    CONTROLLED_EVENT_INJECTION = "controlled_event_injection"


class WorldState(Base):
    """PRD 4.2: append-only. Never UPDATEd or DELETEd once created — every
    activated scenario pins to one of these by id, and a later reset must
    never invalidate an in-flight scenario's reference (PRD 9.2 row 7)."""

    __tablename__ = "world_state"
    __table_args__ = (CheckConstraint("id != parent_id", name="ck_world_state_no_self_parent"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    kind: Mapped[WorldStateKind] = mapped_column(
        pg_enum(WorldStateKind, "world_state_kind"), nullable=False
    )
    simulation_date: Mapped[date] = mapped_column(Date, nullable=False)
    seed: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live.world_state.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class SimulationClock(Base):
    """Singleton: `id` is pinned to 1 by the CHECK constraint, so a second
    row can never be inserted — 'the current simulated business date' stays
    unambiguous (PRD 4.2)."""

    __tablename__ = "simulation_clock"
    __table_args__ = (CheckConstraint("id = 1", name="ck_simulation_clock_singleton"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    simulation_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[ClockStatus] = mapped_column(
        pg_enum(ClockStatus, "clock_status"), nullable=False
    )
    last_advanced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_world_state_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live.world_state.id"), nullable=True
    )
