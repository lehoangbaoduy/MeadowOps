import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


class ReportingInventorySnapshot(Base):
    """Unit 17 (MEADOWOPS-DOM-009): the Reporting layer's own copy of
    inventory positions (PRD 4.1, S1-FR-9) — deliberately distinct from
    `live.inventory_snapshot`, populated on a lag by
    app.services.reporting_sync rather than read live. Lives in the
    `reporting` schema Migration 0001 already created and locked down
    (REVOKE ALL from PUBLIC/meadowops_sandbox, same as `live`) — this unit
    only adds tables to an already-provisioned, already-access-controlled
    schema.

    Same (snapshot_date, product_id, warehouse_id) grain as
    live.inventory_snapshot so the two are directly comparable, but no
    row here is ever overwritten in place: each sync either inserts the
    next day's row for an entity, or — for the one seeded SR-4 conflict
    entity (app.domain.reporting_sync.pick_conflict_entity) — inserts
    nothing further at all, so that entity's single, permanently
    corrupted row is what "frozen artifact of one bad sync" (SR-4) means
    concretely: a row that stops advancing while live keeps moving.
    """

    __tablename__ = "inventory_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_date",
            "product_id",
            "warehouse_id",
            name="uq_reporting_inventory_snapshot_grain",
        ),
        {"schema": "reporting"},
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    product_id: Mapped[str] = mapped_column(String, ForeignKey("live.product.id"), nullable=False)
    warehouse_id: Mapped[str] = mapped_column(
        String, ForeignKey("live.warehouse.id"), nullable=False
    )
    quantity_on_hand: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_allocated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ReportingSyncState(Base):
    """Singleton row (id="default") tracking how far the Reporting layer
    has been synced, and which one (product_id, warehouse_id) pair was
    permanently designated as the SR-4 conflict entity on the layer's
    first-ever sync. `.with_for_update()` on this row is this module's
    concurrency guard — same singleton-row-lock convention as
    app.services.simulation_clock_ops._lock_clock, not an advisory lock,
    since there is a real row here to pin."""

    __tablename__ = "sync_state"
    __table_args__ = {"schema": "reporting"}

    id: Mapped[str] = mapped_column(String, primary_key=True)
    last_synced_simulation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    frozen_conflict_product_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("live.product.id"), nullable=True
    )
    frozen_conflict_warehouse_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("live.warehouse.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), onupdate=text("now()")
    )
