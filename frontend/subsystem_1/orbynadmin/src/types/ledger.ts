/**
 * Unit 24 (MEADOWOPS-DOM-018): hand-declared response types for the
 * Decision & Event Ledger API - same convention (and the same drift risk,
 * Unit 12c's code review) as ExceptionFlag/CustomerRow: these can silently
 * drift from app/schemas/ledger.py on a field rename with no compile-time
 * signal.
 */

export type DecisionEventStatus =
  | "proposed"
  | "clarification_requested"
  | "accepted"
  | "rejected"
  | "implemented"
  | "partially_implemented"
  | "outcome_observed"
  | "stale";

export type DecisionOutcome =
  | "succeeded"
  | "partially_succeeded"
  | "failed"
  | "unintended_consequence"
  | "insufficient_evidence";

export type DecisionEvent = {
  id: string;
  record_type: "operational_event" | "decision";
  status: DecisionEventStatus;
  scenario_id: string | null;
  entity_type: "supplier" | "warehouse" | "product" | "customer" | "carrier";
  entity_id: string;
  title: string;
  summary: string;
  proposed_at: string;
  approval_authority: "manager" | "procurement_operations" | "informational_only" | null;
  decided_at: string | null;
  decided_by: string | null;
  implemented_at: string | null;
  outcome: DecisionOutcome | null;
  outcome_recorded_at: string | null;
  outcome_notes: string | null;
  stale_flagged_at: string | null;
  supersedes_id: string | null;
  created_at: string;
};

export const DECISION_STATUS_LABEL: Record<DecisionEventStatus, string> = {
  proposed: "Proposed",
  clarification_requested: "Clarification Requested",
  accepted: "Accepted",
  rejected: "Rejected",
  implemented: "Implemented",
  partially_implemented: "Partially Implemented",
  outcome_observed: "Outcome Observed",
  stale: "Stale",
};

export const DECISION_OUTCOME_LABEL: Record<DecisionOutcome, string> = {
  succeeded: "Succeeded",
  partially_succeeded: "Partially Succeeded",
  failed: "Failed",
  unintended_consequence: "Unintended Consequence",
  insufficient_evidence: "Insufficient Evidence",
};

// Unit 34 (write actions): mirrors app/schemas/ledger.py's request bodies.
export type ApprovalAuthority = "manager" | "procurement_operations" | "informational_only";
export type EntityType = "supplier" | "warehouse" | "product" | "customer" | "carrier";

export type DecisionProposeRequest = {
  entity_type: EntityType;
  entity_id: string;
  title: string;
  summary: string;
  approval_authority?: ApprovalAuthority;
};

export const ENTITY_TYPE_OPTIONS: { value: EntityType; label: string }[] = [
  { value: "supplier", label: "Supplier" },
  { value: "warehouse", label: "Warehouse" },
  { value: "product", label: "Product" },
  { value: "customer", label: "Customer" },
  { value: "carrier", label: "Carrier" },
];

export const APPROVAL_AUTHORITY_OPTIONS: { value: ApprovalAuthority; label: string }[] = [
  { value: "manager", label: "Manager" },
  { value: "procurement_operations", label: "Procurement Operations" },
  { value: "informational_only", label: "Informational Only" },
];

export const DECISION_OUTCOME_OPTIONS: { value: DecisionOutcome; label: string }[] = [
  { value: "succeeded", label: "Succeeded" },
  { value: "partially_succeeded", label: "Partially Succeeded" },
  { value: "failed", label: "Failed" },
  { value: "unintended_consequence", label: "Unintended Consequence" },
  { value: "insufficient_evidence", label: "Insufficient Evidence" },
];
