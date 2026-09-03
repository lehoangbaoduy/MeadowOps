import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


class ExceptionFlag(Base):
    """Unit 15 (MEADOWOPS-DOM-008): one row per detected exception (S1-FR-4).
    `category` is a plain FK to `live.exception_rule_threshold.id`, not a
    separate Python enum — that table is already the registry of rule
    identities and is Analyst-mutable at runtime (S1-FR-10), so a second
    parallel name for the same three rules would just be a second source of
    truth to keep in sync.

    Only the columns relevant to `category` are populated — low_stock uses
    product_id/warehouse_id, at_risk_po uses purchase_order_id,
    late_shipment uses shipment_id; the others stay NULL for that row. An
    open flag (resolved_at IS NULL) auto-resolves once a later evaluation
    finds the condition no longer holds (app.services.exception_engine),
    rather than being deleted — so `resolved_at` is itself the audit trail
    of when a condition cleared, not just whether it's currently open.
    A flag is never resolved on an inconclusive evaluation (e.g. an
    undefined days-of-supply ratio) — only on a confident "no longer
    flagged" verdict (security review, HIGH; see Evaluation's docstring
    in app.services.exception_engine).

    threshold_value is captured at detection time and never rewritten
    while the flag stays open (security review, MEDIUM: an earlier draft
    re-wrote it on every sync) — so a later Analyst threshold change
    (S1-FR-10) can't retroactively rewrite what actually triggered this
    flag. first_detected_simulation_date is likewise write-once, set only
    when the row is first created; simulation_date instead tracks the
    most recent evaluation that still found the condition true (the
    "last observed" date, distinct from "first detected") — both matter
    for an Analyst asking "how long has this been open?" (S1-FR-4/5).
    """

    __tablename__ = "exception_flag"

    id: Mapped[uuid.UUID] = _uuid_pk()
    category: Mapped[str] = mapped_column(
        String, ForeignKey("live.exception_rule_threshold.id"), nullable=False
    )
    product_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("live.product.id"), nullable=True
    )
    warehouse_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("live.warehouse.id"), nullable=True
    )
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live.purchase_order.id"), nullable=True
    )
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live.shipment.id"), nullable=True
    )
    simulation_date: Mapped[date] = mapped_column(Date, nullable=False)
    first_detected_simulation_date: Mapped[date] = mapped_column(Date, nullable=False)
    measured_value: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    threshold_value: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
