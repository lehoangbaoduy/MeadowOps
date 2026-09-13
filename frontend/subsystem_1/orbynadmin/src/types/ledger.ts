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
