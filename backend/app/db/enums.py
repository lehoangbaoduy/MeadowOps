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


class UserRole(str, enum.Enum):
    """Unit 17a (MEADOWOPS-DOM-010) — Admin (Builder) can write master data
    and use every admin panel control; Analyst can view everything
    Subsystem 1 exposes but cannot write anywhere (PRD 5.1/8.4 amendment)."""

    ADMIN = "admin"
    ANALYST = "analyst"


class ScheduledTickStatus(str, enum.Enum):
    """Unit 13 (MEADOWOPS-DOM-006) — outcome of one scheduled procure-to-stock
    / order-to-ship tick, not the simulation clock's own running/paused
    status (app.domain.simulation_clock.ClockStatus)."""

    SUCCESS = "success"
    FAILED = "failed"


class ScenarioType(str, enum.Enum):
    """Unit 18 (MEADOWOPS-DOM-011) — PRD 6.2's six scenario types."""

    STAKEHOLDER_REQUEST = "stakeholder_request"
    DATA_QUALITY_ISSUE = "data_quality_issue"
    ROOT_CAUSE_INVESTIGATION = "root_cause_investigation"
    SUPPLIER_VENDOR_DECISION = "supplier_vendor_decision"
    PROCESS_BREAKDOWN = "process_breakdown"
    EXECUTIVE_REPORTING = "executive_reporting"


class CompetencyCluster(str, enum.Enum):
    """Unit 18 (MEADOWOPS-DOM-011) — PRD 6.7's three competency clusters.
    Distinct from the Analyst's own hidden-until-monthly-review competency
    assessment; this is Builder-set scenario metadata."""

    ANALYSIS_DIAGNOSIS = "analysis_diagnosis"
    JUDGMENT_DELIVERY = "judgment_delivery"
    COMMUNICATION = "communication"


class DifficultyTier(str, enum.Enum):
    """Unit 18 (MEADOWOPS-DOM-011) — PRD 6.7's three difficulty tiers."""

    FOUNDATIONAL = "foundational"
    STANDARD = "standard"
    STRETCH = "stretch"


class ScenarioSource(str, enum.Enum):
    """Unit 18 (MEADOWOPS-DOM-011) — provenance of a scenario's seeded
    imperfection. exception_flag (DD-24 point 2) is the only source this
    unit implements; manual is reserved for a future free-text authoring
    path, not built here."""

    EXCEPTION_FLAG = "exception_flag"
    MANUAL = "manual"


class ScenarioStatus(str, enum.Enum):
    """Unit 18 (MEADOWOPS-DOM-011) — draft/approved/active/cancelled state
    machine (app.domain.scenario.VALID_TRANSITIONS is the single source of
    truth for which transitions are legal)."""

    DRAFT = "draft"
    APPROVED = "approved"
    ACTIVE = "active"
    CANCELLED = "cancelled"


class QueryStatementType(str, enum.Enum):
    """Unit 19 (MEADOWOPS-DOM-012) — QueryLog.statement_type, the whole
    submission's overall classification (app.domain.query_playground.
    overall_statement_type), reusing app.domain.query_classifier's own
    three-way read/write/unknown split rather than inventing a new one."""

    READ = "read"
    WRITE = "write"
    UNKNOWN = "unknown"


class QueryResultStatus(str, enum.Enum):
    """Unit 19 (MEADOWOPS-DOM-012) — QueryLog.result_status. Mirrors
    app.domain.query_playground.QuerySubmissionStatus's three terminal
    states plus CANCELLED (an explicit decline at the confirmation dialog,
    S1-FR-14's "executed or cancelled"). received/confirmation_required/
    executing are in-flight-only states with nothing to log yet, so they
    have no QueryLog counterpart here."""

    SUCCESS = "success"
    ERROR = "error"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class StakeholderPersona(str, enum.Enum):
    """Unit 21a (MEADOWOPS-DOM-014, PRD 6.5): the fixed 6-persona set a
    ChatThread is locked to for its whole life (DD-25). A closed,
    PRD-defined label set, not an admin-editable entity — the richer
    Stakeholder Persona table Appendix B names separately (priorities,
    style, any future prompt-config content) is U23's to build if its
    roleplay AI ever needs more than a name; this unit only needs a
    discriminator ChatThread's own uniqueness constraint can key on."""

    OPERATIONS_MANAGER = "operations_manager"
    PROCUREMENT_MANAGER = "procurement_manager"
    WAREHOUSE_MANAGER = "warehouse_manager"
    IT_MANAGER = "it_manager"
    OPERATIONS_DIRECTOR = "operations_director"
    CFO = "cfo"
