import enum


class SourceSystem(str, enum.Enum):
    """PRD 4.1 — conceptual origin tag, not a separate physical system."""

    ERP = "erp"
    WMS = "wms"
    PROCUREMENT = "procurement"


class ProductCategory(str, enum.Enum):
    CORRUGATED_PACKAGING = "corrugated_packaging"
    PROTECTIVE_PACKAGING = "protective_packaging"
    SHIPPING_LABELING_SUPPLIES = "shipping_labeling_supplies"


class CostTier(str, enum.Enum):
    LOW = "low"
    MID = "mid"
    HIGH = "high"


class Variability(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ServicePriority(str, enum.Enum):
    STANDARD = "standard"
    PRIORITY = "priority"
    CRITICAL = "critical"


class PurchaseOrderStatus(str, enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class SalesOrderStatus(str, enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    ALLOCATED = "allocated"
    PARTIALLY_SHIPPED = "partially_shipped"
    SHIPPED = "shipped"
    CANCELLED = "cancelled"


class ShipmentStatus(str, enum.Enum):
    PENDING = "pending"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    EXCEPTION = "exception"


class TransferStatus(str, enum.Enum):
    PENDING = "pending"
    IN_TRANSIT = "in_transit"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class InventoryTransactionType(str, enum.Enum):
    RECEIPT = "receipt"
    SHIPMENT = "shipment"
    ADJUSTMENT = "adjustment"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    CYCLE_COUNT = "cycle_count"
