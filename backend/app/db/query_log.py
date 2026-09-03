"""Unit 19 (MEADOWOPS-DOMAIN-010, spec MEADOWOPS-DOM-012, PRD 5.9/S1-FR-14):
one row per Query Playground submission that reached a terminal outcome
(executed or explicitly cancelled at the confirmation dialog) — never for a
submission still only at the "did this need confirmation" preview step,
since nothing has actually happened yet at that point (app.services.
query_execution never writes a row until execute or cancel-confirmation is
called).

Lives in `live` (Subsystem 1 operational data, like every other table this
subsystem's own API layer writes) even though the admin panel eventually
reads it too (PRD 328, §6.12, Unit 28) - Subsystem 2 only ever reaches this
through Subsystem 1's own API layer (8.4's one-boundary rule), never via a
direct cross-schema query, so there's no reason to special-case its schema.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base, pg_enum
from app.db.enums import QueryResultStatus, QueryStatementType


class QueryLog(Base):
    __tablename__ = "query_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live.user.id"), nullable=False
    )
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    statement_type: Mapped[QueryStatementType] = mapped_column(
        pg_enum(QueryStatementType, "query_statement_type"), nullable=False
    )
    result_status: Mapped[QueryResultStatus] = mapped_column(
        pg_enum(QueryResultStatus, "query_result_status"), nullable=False
    )
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
