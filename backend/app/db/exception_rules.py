from sqlalchemy import Boolean, CheckConstraint, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ExceptionRuleThreshold(Base, TimestampMixin):
    """Builder-set default thresholds for Subsystem 1's exception rules
    (S1-FR-4), pending Analyst review/adjustment once Active Use begins
    (S1-FR-10, PRD 5.7) - the same "reasonable default, not final" posture
    PRD line 207 applies to the KPI SQL in app/domain/kpi_sql.py.

    Runtime-mutable via the admin Settings page (PRD Appendix D line 627)
    once a later unit wires that CRUD surface - that's why this is a table
    and not a Python constant, unlike the KPI SQL (see kpi_sql.py's
    docstring for that distinction). The actual exception-flagging logic
    that reads these values is Unit 15's exception engine
    (MEADOWOPS-DOMAIN-007); this table only holds the current threshold
    values and their metadata, not the evaluation logic itself.
    """

    __tablename__ = "exception_rule_threshold"
    __table_args__ = (
        CheckConstraint(
            "threshold_value >= 0", name="ck_exception_rule_threshold_non_negative"
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    threshold_value: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    unit: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
