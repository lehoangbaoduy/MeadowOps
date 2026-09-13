"""Unit 25 (MEADOWOPS-DOM-019, PRD 6.6 steps 8-9, 6.8): pure domain-layer
prompt building, response parsing, and the one-automatic-retry Claude
orchestration (PRD 9.2) for the AI evaluation framework - mirrors
app.domain.persona_chat's shape (Unit 23) exactly. Not extracted into a
shared retry helper, matching that module's own stated convention (a third
occurrence of the loop body, not yet a real abstraction - the retryable-
exception tuple and terminal exception type still differ per call site).

No DB or session access here - app.services.evaluation is the one module
that knows about ChatThread/ChatMessage/Scenario/Evaluation and calls into
this module.

EVALUATION_TEMPLATE's required_context maps onto PRD 6.8's own list
("ground truth, evidence, stakeholder context, expected cluster behaviors,
the Analyst's responses, and the outcome") as follows - a scope decision
made explicit here since nothing in the codebase before this unit ever
consumed this template:

- ground_truth_package: the scenario's full, unredacted `Scenario.
  ground_truth` dict (every key) - the complete answer key. Same meaning
  already established by app.domain.persona_chat.run_sufficiency_check's
  own "ground_truth_package" context key.
- evidence_package: the world-state-facts-only projection (known_cause +
  evidence) app.domain.persona_chat.build_known_information already builds
  for the persona roleplay - reused here, not reimplemented, as "the
  evidence the Analyst actually had access to during the scenario".
- outcome: the scenario's resolution/conclusion content (acceptable_
  conclusions, unacceptable_conclusions, uncertainty) - "the outcome" read
  as "what the correct resolution is", the one ground_truth projection
  ground_truth_package/evidence_package above don't already cover on
  their own terms. Explicitly NOT DecisionEvent.outcome (Unit 24's Ledger)
  - PRD 6.6 orders step 10 (Ledger recording) after step 9 (evaluation),
  so a real-world ledger outcome cannot be an input to the evaluation that
  precedes it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.db.enums import CompetencyCluster, DifficultyRecommendation
from app.domain.claude_client import ClaudeAPIError, ClaudeClient
from app.domain.prompt_templates import EVALUATION_TEMPLATE

# Transcribed directly from PRD 6.7's cluster rollup table - Builder-
# authored, version-controlled content, the same "who mutates it and when"
# reasoning as app.domain.persona_chat.PERSONA_PROFILES and DD-14/DD-15's
# KPI SQL.
EXPECTED_CLUSTER_BEHAVIORS: dict[CompetencyCluster, str] = {
    CompetencyCluster.ANALYSIS_DIAGNOSIS: (
        "KPI interpretation, data investigation/SQL literacy, root-cause "
        "analysis, data-quality awareness"
    ),
    CompetencyCluster.JUDGMENT_DELIVERY: (
        "Requirements elicitation, decision-making, process improvement, "
        "technical delivery/UAT"
    ),
    CompetencyCluster.COMMUNICATION: "Stakeholder and executive/business communication",
}

# Placeholder pending the real Anthropic SDK adapter (Phase 4, blocker B3) -
# see app.domain.scenario_generation's identical constant.
_CLAUDE_MODEL = "claude-sonnet-4-5"
_MAX_TOKENS = 2048
# PRD 9.2: exactly one automatic retry (the original call plus one retry).
_MAX_ATTEMPTS = 2

_OUTCOME_KEYS = ("acceptable_conclusions", "unacceptable_conclusions", "uncertainty")

_REQUIRED_STRING_KEYS = (
    "strengths",
    "gaps",
    "evidence",
    "senior_analyst_pushback",
    "final_verdict",
    "suggested_next_skill_focus",
)

_VALID_DIFFICULTY_RECOMMENDATIONS = {member.value for member in DifficultyRecommendation}

# EVALUATION_TEMPLATE (frozen v1, ER-6: never edited) has no JSON response-
# format instructions of its own - unlike SUFFICIENCY_CHECK_TEMPLATE, it
# predates any structured-output requirement. Appended as a separate,
# unversioned suffix at call time, the exact precedent app.domain.
# scenario_generation's own docstring established for GENERATION_TEMPLATE.
#
# Security review of this unit, MEDIUM: senior_analyst_pushback is - like
# app.domain.persona_chat's own suggest_pushback_message - text a Builder
# may paste verbatim into the thread the Analyst reads, generated here
# against the *full*, unredacted ground_truth_package (unlike the persona
# roleplay's redacted known_information). Without an explicit instruction,
# nothing stops the model from restating a specific ground-truth fact
# (a supporting signal, distractor, expected consideration, or conclusion)
# directly in that field, leaking the answer key through a human-approved
# relay - the same leak class SUFFICIENCY_CHECK_TEMPLATE's own
# suggested_pushback instruction (app.domain.prompt_templates) was already
# written to close. Mirrored here verbatim rather than only relying on
# EVALUATION_TEMPLATE's own "no single number is the sole representation"
# framing, which is about grading philosophy, not leakage.
_RESPONSE_FORMAT_INSTRUCTIONS = (
    "\n\nRespond with ONLY a single JSON object (no prose, no markdown "
    "fences) with exactly these keys, every value a non-empty string: "
    '"strengths", "gaps", "evidence", "senior_analyst_pushback", '
    '"final_verdict", "suggested_next_skill_focus", and '
    '"difficulty_recommendation" (one of "foundational", "standard", '
    '"stretch", or "hold" - "hold" when the evidence in this one thread is '
    "not enough on its own to recommend a tier). Never state a specific "
    "ground-truth fact (a supporting signal, distractor, expected "
    "consideration, or conclusion) directly in senior_analyst_pushback - a "
    "Builder may paste it straight into the thread the Analyst is meant to "
    "investigate independently. Phrase it only as a Socratic nudge."
)


class EvaluationSchemaError(ValueError):
    """Malformed/incomplete AI response (PRD 6.8/9.2) - not valid JSON, not
    an object, or missing/mistyping a required key."""


class EvaluationGenerationFailedError(Exception):
    """Raised once the one automatic retry (PRD 9.2) is exhausted."""

    def __init__(self, last_error: Exception) -> None:
        self.last_error = last_error
        super().__init__(f"evaluation generation failed after one retry: {last_error}")


@dataclass(frozen=True)
class EvaluationResult:
    strengths: str
    gaps: str
    evidence: str
    senior_analyst_pushback: str
    final_verdict: str
    suggested_next_skill_focus: str
    difficulty_recommendation: DifficultyRecommendation
    raw_response: str


def build_outcome(ground_truth: dict) -> dict:
    """See module docstring - the resolution/conclusion projection of
    ground_truth, distinct from the full ground_truth_package and from
    evidence_package's known_cause/evidence projection."""
    return {key: ground_truth[key] for key in _OUTCOME_KEYS if key in ground_truth}


def build_evaluation_prompt(
    *,
    ground_truth_package: dict,
    evidence_package: dict,
    stakeholder_context: str,
    expected_cluster_behaviors: str,
    analyst_responses: str,
    outcome: dict,
) -> str:
    rendered = EVALUATION_TEMPLATE.render(
        {
            "ground_truth_package": json.dumps(ground_truth_package, sort_keys=True, default=str),
            "evidence_package": json.dumps(evidence_package, sort_keys=True, default=str),
            "stakeholder_context": stakeholder_context,
            "expected_cluster_behaviors": expected_cluster_behaviors,
            "analyst_responses": analyst_responses,
            "outcome": json.dumps(outcome, sort_keys=True, default=str),
        }
    )
    return rendered + _RESPONSE_FORMAT_INSTRUCTIONS


def parse_evaluation_response(content: str) -> EvaluationResult:
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, RecursionError) as exc:
        # Security review precedent from Unit 22/23: json.loads on
        # sufficiently deeply-nested input raises RecursionError, not
        # JSONDecodeError - both are "malformed input" and fold into the
        # same clean schema error rather than an unhandled 500.
        raise EvaluationSchemaError(f"response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise EvaluationSchemaError("response JSON must be an object")

    values: dict[str, str] = {}
    for key in _REQUIRED_STRING_KEYS:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise EvaluationSchemaError(f'"{key}" must be a non-empty string')
        values[key] = value

    difficulty_recommendation = payload.get("difficulty_recommendation")
    if difficulty_recommendation not in _VALID_DIFFICULTY_RECOMMENDATIONS:
        raise EvaluationSchemaError(
            '"difficulty_recommendation" must be one of '
            f"{sorted(_VALID_DIFFICULTY_RECOMMENDATIONS)}"
        )

    return EvaluationResult(
        **values,
        difficulty_recommendation=DifficultyRecommendation(difficulty_recommendation),
        raw_response=content,
    )


def generate_evaluation(
    client: ClaudeClient,
    *,
    ground_truth_package: dict,
    evidence_package: dict,
    stakeholder_context: str,
    expected_cluster_behaviors: str,
    analyst_responses: str,
    outcome: dict,
) -> EvaluationResult:
    """One automatic retry on a Claude API error/timeout or malformed/
    incomplete output (PRD 9.2) - a second consecutive failure of either
    kind is surfaced as EvaluationGenerationFailedError."""
    prompt = build_evaluation_prompt(
        ground_truth_package=ground_truth_package,
        evidence_package=evidence_package,
        stakeholder_context=stakeholder_context,
        expected_cluster_behaviors=expected_cluster_behaviors,
        analyst_responses=analyst_responses,
        outcome=outcome,
    )
    last_error: Exception | None = None
    for _attempt in range(_MAX_ATTEMPTS):
        try:
            response = client.create_message(
                model=_CLAUDE_MODEL,
                system=(
                    "You are a senior analyst drafting a DRAFT, NOT "
                    "AUTHORITATIVE evaluation of a trainee Analyst's "
                    "performance on a supply-chain scenario. You respond "
                    "with JSON only, never prose."
                ),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=_MAX_TOKENS,
            )
            return parse_evaluation_response(response.content)
        except (ClaudeAPIError, EvaluationSchemaError) as exc:
            last_error = exc
    assert last_error is not None  # every loop iteration above sets it on failure
    raise EvaluationGenerationFailedError(last_error)
