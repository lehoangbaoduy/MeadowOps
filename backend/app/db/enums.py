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


class ChatThreadStatus(str, enum.Enum):
    """Unit 25 (MEADOWOPS-DOM-019, PRD 6.1/6.6 steps 8-9): a minimal
    two-state addition to ChatThread, not PRD 6.1's full nine-state work
    lifecycle (Draft/Open/Awaiting Analyst/Awaiting Stakeholder Reply/
    Deadline Approaching/Overdue/Under AI Evaluation/Pending Human Review/
    Completed). Pending Human Review is U26's (Human Review table). OPEN
    covers every pre-completion state this codebase already models
    implicitly via message history; COMPLETED is the one transition PRD
    6.6 step 8 actually requires - "the Builder marks the thread
    Completed", which synchronously triggers step 9's evaluation
    (app.services.evaluation.complete_thread_and_generate_evaluation).
    No persisted "under evaluation" state on purpose - evaluation runs
    inside that one request/transaction, so there is nothing for a thread
    to be stuck in if it fails; see that module's docstring.

    Unit 30a (MEADOWOPS-UI-003, B12) is the notification/deadline-driven
    states' owning unit, and deliberately did NOT expand this enum to add
    them: ChatThread.deadline_at/deadline_approaching_notified/
    overdue_notified (app.db.chat) model "approaching"/"overdue" as a
    derived condition over a still-OPEN thread, not a new persisted
    status. Adding real DEADLINE_APPROACHING/OVERDUE members would break
    send_message's `status == COMPLETED` guard's implicit "anything else
    is still open" assumption and every existing `status == OPEN` filter
    (app.services.evaluation, app.services.portfolio, app.services.
    scenario_service) without providing anything a derived column can't."""

    OPEN = "open"
    COMPLETED = "completed"


class NotificationKind(str, enum.Enum):
    """Unit 30a (MEADOWOPS-UI-003, PRD 6.1, B12 follow-on to U30): the two
    notification kinds with a real, testable producer during Build & Test
    - both written only by app.services.notifications.sweep_thread_
    deadlines. PRD 6.1 names two more kinds this project deliberately does
    NOT model as Notification rows: "new message" is already served by the
    existing unread-badge mechanism (U21, ChatThreadReadState/
    list_threads_with_unread) - a second, redundant row per message would
    duplicate a working mechanism on the hottest write path in this
    codebase for no closed catalog row. "monthly review available" has no
    producer at all yet - PRD 6.9's own text is explicit that the monthly
    review cadence itself doesn't start until Active Use, so there is
    nothing to notify about during Build & Test; adding the member now
    would be a dead branch no test could exercise."""

    DEADLINE_APPROACHING = "deadline_approaching"
    DEADLINE_MISSED = "deadline_missed"


class DifficultyRecommendation(str, enum.Enum):
    """Unit 25 (MEADOWOPS-DOM-019, PRD 6.7): the AI evaluator's per-thread
    difficulty-tier recommendation for its scenario's single competency
    cluster (engine.scenario.competency_cluster is one enum value per
    scenario, not a set - PRD 6.7's "most scenarios naturally exercise two
    of the three clusters" nuance is deferred, not modeled, rather than
    guessing an unbacked multi-cluster shape). The three DifficultyTier
    values plus HOLD, PRD 6.7's own defined "hold, insufficient evidence"
    valid result - never a forced tier change."""

    FOUNDATIONAL = "foundational"
    STANDARD = "standard"
    STRETCH = "stretch"
    HOLD = "hold"


class HumanReviewVerdict(str, enum.Enum):
    """Unit 26 (MEADOWOPS-DOM-020, PRD 6.6 step 11, ER-3/ER-4): a monthly
    reviewer's verdict on one Evaluation row's own
    `difficulty_recommendation` - PRD's edge case #29, "reviewer overrides
    an AI tier recommendation, logged distinctly from simple agreement".
    AGREE needs no further payload; OVERRIDE requires
    HumanReview.overridden_recommendation to carry the reviewer's own call
    (enforced by both a Pydantic model validator and a DB CHECK constraint,
    migration 0021) - ER-3 frames this as a logged learning artifact, not a
    correction, so the schema never conflates "reviewer disagreed" with
    "evaluation was wrong"."""

    AGREE = "agree"
    OVERRIDE = "override"


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
