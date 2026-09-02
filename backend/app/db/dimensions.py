from datetime import date

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, pg_enum
from app.db.enums import CostTier, ProductCategory, ServicePriority, Variability


class Product(Base, TimestampMixin):
    __tablename__ = "product"
    __table_args__ = (CheckConstraint("unit_cost >= 0", name="ck_product_unit_cost_non_negative"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    sku: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[ProductCategory] = mapped_column(
        pg_enum(ProductCategory, "product_category"), nullable=False
    )
    unit_cost: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Warehouse(Base, TimestampMixin):
    __tablename__ = "warehouse"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    region: Mapped[str] = mapped_column(String, nullable=False)
    capacity_pallet_positions: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Supplier(Base, TimestampMixin):
    __tablename__ = "supplier"
    __table_args__ = (
        CheckConstraint(
            "historical_otif_pct >= 0 AND historical_otif_pct <= 100",
            name="ck_supplier_otif_pct_range",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    category_focus: Mapped[str] = mapped_column(String, nullable=False)
    unit_cost_tier: Mapped[CostTier] = mapped_column(
        pg_enum(CostTier, "cost_tier"), nullable=False
    )
    base_lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    lead_time_variability: Mapped[Variability] = mapped_column(
        pg_enum(Variability, "variability"), nullable=False
    )
    historical_otif_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Customer(Base, TimestampMixin):
    __tablename__ = "customer"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    service_priority: Mapped[ServicePriority] = mapped_column(
        pg_enum(ServicePriority, "service_priority"), nullable=False
    )
    warehouse_id: Mapped[str] = mapped_column(
        String, ForeignKey("live.warehouse.id"), nullable=False
    )
    region: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Carrier(Base, TimestampMixin):
    __tablename__ = "carrier"
    __table_args__ = (
        CheckConstraint(
            "reliability_pct >= 0 AND reliability_pct <= 100", name="ck_carrier_reliability_pct_range"
        ),
        CheckConstraint(
            "transit_days_min <= transit_days_max", name="ck_carrier_transit_days_ordered"
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    transit_days_min: Mapped[float] = mapped_column(Numeric(4, 1), nullable=False)
    transit_days_max: Mapped[float] = mapped_column(Numeric(4, 1), nullable=False)
    variability: Mapped[Variability] = mapped_column(
        pg_enum(Variability, "variability"), nullable=False
    )
    reliability_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class DateDim(Base):
    __tablename__ = "date_dim"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    day: Mapped[int] = mapped_column(Integer, nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    is_month_end: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_quarter_end: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_year_end: Mapped[bool] = mapped_column(Boolean, nullable=False)
