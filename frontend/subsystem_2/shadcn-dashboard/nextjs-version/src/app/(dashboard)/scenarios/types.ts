/**
 * Unit 20a (MEADOWOPS-UI-002): mirrors backend/app/schemas/scenario.py's
 * ScenarioRead/ScenarioCreate/GroundTruthUpdate and
 * backend/app/schemas/dashboard.py's ExceptionFlagRead — kept in sync by
 * hand (no shared codegen in this project), not by import, since the two
 * apps are separate build targets.
 */

export type ScenarioType =
  | "stakeholder_request"
  | "data_quality_issue"
  | "root_cause_investigation"
  | "supplier_vendor_decision"
  | "process_breakdown"
  | "executive_reporting";

export type CompetencyCluster = "analysis_diagnosis" | "judgment_delivery" | "communication";

export type DifficultyTier = "foundational" | "standard" | "stretch";

export type ScenarioStatus = "draft" | "approved" | "active" | "cancelled";

export interface ScenarioGroundTruth {
  known_cause: string;
  evidence: {
    source_exception_flag_id: string;
    category: string;
    product_id: string | null;
    warehouse_id: string | null;
    purchase_order_id: string | null;
    shipment_id: string | null;
    simulation_date: string;
    first_detected_simulation_date: string;
    measured_value: string | null;
    threshold_value: string;
  };
  supporting_signals: string[];
  distractors: string[];
  expected_considerations: string[];
  acceptable_conclusions: string[];
  unacceptable_conclusions: string[];
  uncertainty: string;
}

export interface Scenario {
  id: string;
  title: string;
  scenario_type: ScenarioType;
  competency_cluster: CompetencyCluster;
  difficulty_tier: DifficultyTier;
  source: "exception_flag" | "manual";
  source_exception_flag_id: string | null;
  ground_truth: ScenarioGroundTruth;
  status: ScenarioStatus;
  created_by: string;
  approved_at: string | null;
  activated_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ExceptionFlag {
  id: string;
  category: string;
  product_id: string | null;
  warehouse_id: string | null;
  purchase_order_id: string | null;
  shipment_id: string | null;
  simulation_date: string;
  first_detected_simulation_date: string;
  measured_value: string | null;
  threshold_value: string;
  detected_at: string;
  resolved_at: string | null;
}

export const SCENARIO_TYPE_OPTIONS: { value: ScenarioType; label: string }[] = [
  { value: "stakeholder_request", label: "Stakeholder Request" },
  { value: "data_quality_issue", label: "Data Quality Issue" },
  { value: "root_cause_investigation", label: "Root Cause Investigation" },
  { value: "supplier_vendor_decision", label: "Supplier/Vendor Decision" },
  { value: "process_breakdown", label: "Process Breakdown" },
  { value: "executive_reporting", label: "Executive Reporting" },
];

export const COMPETENCY_CLUSTER_OPTIONS: { value: CompetencyCluster; label: string }[] = [
  { value: "analysis_diagnosis", label: "Analysis & Diagnosis" },
  { value: "judgment_delivery", label: "Judgment & Delivery" },
  { value: "communication", label: "Communication" },
];

export const DIFFICULTY_TIER_OPTIONS: { value: DifficultyTier; label: string }[] = [
  { value: "foundational", label: "Foundational" },
  { value: "standard", label: "Standard" },
  { value: "stretch", label: "Stretch" },
];
