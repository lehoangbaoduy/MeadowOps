/**
 * Unit 34: mirrors backend/app/schemas/chat.py (ThreadReadWithUnread, the
 * fields this page actually uses), app/schemas/evaluation.py
 * (EvaluationRead), app/schemas/human_review.py (HumanReviewCreate/Read),
 * and app/schemas/portfolio.py (PortfolioExportRead) - kept in sync by
 * hand, same convention as ../types.ts's own docstring.
 */

export type ThreadStatus = "open" | "completed";

export type Persona =
  | "operations_manager"
  | "procurement_manager"
  | "warehouse_manager"
  | "it_manager"
  | "operations_director"
  | "cfo";

const PERSONA_LABELS: Record<Persona, string> = {
  operations_manager: "Operations Manager",
  procurement_manager: "Procurement Manager",
  warehouse_manager: "Warehouse Manager",
  it_manager: "IT Manager",
  operations_director: "Operations Director",
  cfo: "CFO",
};

export function personaLabel(persona: string): string {
  return PERSONA_LABELS[persona as Persona] ?? persona;
}

export type ScenarioThread = {
  id: string;
  scenario_id: string;
  persona: Persona;
  status: ThreadStatus;
  created_at: string;
};

export type DifficultyRecommendation = "foundational" | "standard" | "stretch" | "hold";

export type Evaluation = {
  id: string;
  thread_id: string;
  prompt_version: string;
  strengths: string;
  gaps: string;
  evidence: string;
  senior_analyst_pushback: string;
  final_verdict: string;
  suggested_next_skill_focus: string;
  difficulty_recommendation: DifficultyRecommendation;
  created_at: string;
};

export type HumanReviewVerdict = "agree" | "override";

export type HumanReview = {
  id: string;
  evaluation_id: string;
  reviewer_name: string;
  verdict: HumanReviewVerdict;
  tier_assessment_notes: string;
  overridden_recommendation: DifficultyRecommendation | null;
  created_at: string;
};

export type PortfolioMessage = {
  sender_role: "admin" | "analyst";
  body: string;
  sent_at: string;
};

export type PortfolioReflection = {
  reflection_what_happened: string;
  reflection_initial_thought: string;
  reflection_evidence_that_mattered: string;
  reflection_what_missed: string;
  reflection_what_changed_after_pushback: string;
  reflection_what_differently: string;
  reflection_skill_improved: string;
  created_at: string;
};

export type PortfolioExport = {
  scenario: { title: string; scenario_type: string; competency_cluster: string };
  trigger: string | null;
  messages: PortfolioMessage[];
  evaluation: Evaluation;
  human_review: HumanReview | null;
  reflection: PortfolioReflection | null;
};

export const DIFFICULTY_RECOMMENDATION_LABEL: Record<DifficultyRecommendation, string> = {
  foundational: "Foundational",
  standard: "Standard",
  stretch: "Stretch",
  hold: "Hold",
};
