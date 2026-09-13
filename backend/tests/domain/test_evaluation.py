"""Unit 25 (MEADOWOPS-DOM-019, PRD 6.6 steps 8-9, 6.8): pure domain-layer
tests for the AI evaluation framework - prompt building, response parsing,
and the one-automatic-retry orchestration. No DB access - see
app.domain.evaluation's own docstring for why the scenario/thread lookups
live in app.services.evaluation instead."""

from __future__ import annotations

import json

import pytest

from app.db.enums import CompetencyCluster, DifficultyRecommendation
from app.domain.claude_client import ClaudeAPIError, ClaudeResponse, ClaudeTimeoutError, MockClaudeClient
from app.domain.evaluation import (
    EXPECTED_CLUSTER_BEHAVIORS,
    EvaluationGenerationFailedError,
    EvaluationResult,
    EvaluationSchemaError,
    build_evaluation_prompt,
    build_outcome,
    generate_evaluation,
    parse_evaluation_response,
)

_FULL_GROUND_TRUTH = {
    "known_cause": "Reorder point misconfigured for SKU-COR-001 at WH-EAST",
    "evidence": {"product_id": "SKU-COR-001", "warehouse_id": "WH-EAST", "on_hand": 12},
    "supporting_signals": ["signal-lead-time-spike"],
    "distractors": ["distractor-warehouse-relocation"],
    "expected_considerations": ["consideration-check-reorder-point"],
    "acceptable_conclusions": ["conclusion-raise-reorder-point"],
    "unacceptable_conclusions": ["conclusion-blame-supplier"],
    "uncertainty": "moderate confidence in demand forecast",
}

_VALID_PAYLOAD = {
    "strengths": "Correctly identified the reorder point issue.",
    "gaps": "Did not quantify the cost impact.",
    "evidence": "Cited the on-hand count and lead time signal.",
    "senior_analyst_pushback": "What would you check next if wrong?",
    "final_verdict": "Solid investigation, minor gaps.",
    "suggested_next_skill_focus": "Quantifying financial impact.",
    "difficulty_recommendation": "standard",
}


class TestExpectedClusterBehaviors:
    def test_every_competency_cluster_has_a_description(self) -> None:
        assert set(EXPECTED_CLUSTER_BEHAVIORS) == set(CompetencyCluster)

    def test_every_description_is_nonblank(self) -> None:
        assert all(text.strip() for text in EXPECTED_CLUSTER_BEHAVIORS.values())


class TestBuildOutcome:
    def test_includes_only_the_conclusion_keys(self) -> None:
        outcome = build_outcome(_FULL_GROUND_TRUTH)
        assert outcome == {
            "acceptable_conclusions": ["conclusion-raise-reorder-point"],
            "unacceptable_conclusions": ["conclusion-blame-supplier"],
            "uncertainty": "moderate confidence in demand forecast",
        }

    def test_excludes_known_cause_and_evidence(self) -> None:
        outcome = build_outcome(_FULL_GROUND_TRUTH)
        assert "known_cause" not in outcome
        assert "evidence" not in outcome

    def test_tolerates_a_ground_truth_missing_conclusion_keys(self) -> None:
        assert build_outcome({"known_cause": "x"}) == {}


class TestBuildEvaluationPrompt:
    def _prompt(self, **overrides) -> str:
        kwargs = {
            "ground_truth_package": _FULL_GROUND_TRUTH,
            "evidence_package": {"known_cause": "x", "evidence": "y"},
            "stakeholder_context": "CFO (Financial impact; Concise)",
            "expected_cluster_behaviors": "KPI interpretation",
            "analyst_responses": "I checked the reorder point.",
            "outcome": {"uncertainty": "moderate"},
        }
        kwargs.update(overrides)
        return build_evaluation_prompt(**kwargs)

    def test_includes_every_context_section(self) -> None:
        prompt = self._prompt()
        assert "CFO (Financial impact; Concise)" in prompt
        assert "KPI interpretation" in prompt
        assert "I checked the reorder point." in prompt

    def test_includes_json_response_format_instructions(self) -> None:
        prompt = self._prompt()
        assert '"difficulty_recommendation"' in prompt

    def test_instructs_against_leaking_ground_truth_via_senior_analyst_pushback(self) -> None:
        # Security review, MEDIUM: senior_analyst_pushback is a Builder-
        # pasteable field generated against the full ground truth - must
        # carry the same anti-leak instruction SUFFICIENCY_CHECK_TEMPLATE's
        # own suggested_pushback already has.
        prompt = self._prompt()
        assert "senior_analyst_pushback" in prompt.split("Never state a specific")[1]

    def test_does_not_mutate_the_frozen_template_text(self) -> None:
        from app.domain.prompt_templates import EVALUATION_TEMPLATE

        original = EVALUATION_TEMPLATE.template
        self._prompt()
        assert EVALUATION_TEMPLATE.template == original


class TestParseEvaluationResponse:
    def test_parses_a_valid_payload(self) -> None:
        result = parse_evaluation_response(json.dumps(_VALID_PAYLOAD))
        assert result == EvaluationResult(
            strengths=_VALID_PAYLOAD["strengths"],
            gaps=_VALID_PAYLOAD["gaps"],
            evidence=_VALID_PAYLOAD["evidence"],
            senior_analyst_pushback=_VALID_PAYLOAD["senior_analyst_pushback"],
            final_verdict=_VALID_PAYLOAD["final_verdict"],
            suggested_next_skill_focus=_VALID_PAYLOAD["suggested_next_skill_focus"],
            difficulty_recommendation=DifficultyRecommendation.STANDARD,
            raw_response=json.dumps(_VALID_PAYLOAD),
        )

    def test_accepts_hold_as_a_valid_recommendation(self) -> None:
        payload = {**_VALID_PAYLOAD, "difficulty_recommendation": "hold"}
        result = parse_evaluation_response(json.dumps(payload))
        assert result.difficulty_recommendation == DifficultyRecommendation.HOLD

    def test_raises_on_invalid_json(self) -> None:
        with pytest.raises(EvaluationSchemaError):
            parse_evaluation_response("not json")

    def test_raises_a_schema_error_not_a_recursion_error_on_deeply_nested_json(self) -> None:
        deeply_nested = "[" * 200_000
        with pytest.raises(EvaluationSchemaError):
            parse_evaluation_response(deeply_nested)

    def test_raises_when_response_is_a_json_array_not_object(self) -> None:
        with pytest.raises(EvaluationSchemaError):
            parse_evaluation_response("[]")

    @pytest.mark.parametrize("missing_key", list(_VALID_PAYLOAD.keys())[:-1])
    def test_raises_when_a_required_string_key_is_missing(self, missing_key: str) -> None:
        payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != missing_key}
        with pytest.raises(EvaluationSchemaError):
            parse_evaluation_response(json.dumps(payload))

    def test_raises_when_a_required_string_key_is_blank(self) -> None:
        payload = {**_VALID_PAYLOAD, "strengths": "   "}
        with pytest.raises(EvaluationSchemaError):
            parse_evaluation_response(json.dumps(payload))

    def test_raises_on_an_invalid_difficulty_recommendation(self) -> None:
        payload = {**_VALID_PAYLOAD, "difficulty_recommendation": "expert"}
        with pytest.raises(EvaluationSchemaError):
            parse_evaluation_response(json.dumps(payload))

    def test_raises_when_difficulty_recommendation_is_missing(self) -> None:
        payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "difficulty_recommendation"}
        with pytest.raises(EvaluationSchemaError):
            parse_evaluation_response(json.dumps(payload))


class TestGenerateEvaluation:
    def _kwargs(self) -> dict:
        return {
            "ground_truth_package": _FULL_GROUND_TRUTH,
            "evidence_package": {"known_cause": "x", "evidence": "y"},
            "stakeholder_context": "CFO (Financial impact; Concise)",
            "expected_cluster_behaviors": "KPI interpretation",
            "analyst_responses": "I checked the reorder point.",
            "outcome": {"uncertainty": "moderate"},
        }

    def test_succeeds_on_the_first_call(self) -> None:
        client = MockClaudeClient(script=[ClaudeResponse(content=json.dumps(_VALID_PAYLOAD))])
        result = generate_evaluation(client, **self._kwargs())
        assert result.difficulty_recommendation == DifficultyRecommendation.STANDARD

    def test_retries_once_after_a_claude_api_error_then_succeeds(self) -> None:
        client = MockClaudeClient(
            script=[ClaudeAPIError("rate limited"), ClaudeResponse(content=json.dumps(_VALID_PAYLOAD))]
        )
        result = generate_evaluation(client, **self._kwargs())
        assert result.difficulty_recommendation == DifficultyRecommendation.STANDARD

    def test_retries_once_after_a_timeout_then_succeeds(self) -> None:
        client = MockClaudeClient(
            script=[ClaudeTimeoutError("timed out"), ClaudeResponse(content=json.dumps(_VALID_PAYLOAD))]
        )
        generate_evaluation(client, **self._kwargs())

    def test_retries_once_after_malformed_output_then_succeeds(self) -> None:
        client = MockClaudeClient(
            script=[
                ClaudeResponse(content="not json"),
                ClaudeResponse(content=json.dumps(_VALID_PAYLOAD)),
            ]
        )
        generate_evaluation(client, **self._kwargs())

    def test_raises_after_the_retry_is_also_exhausted(self) -> None:
        client = MockClaudeClient(
            script=[ClaudeAPIError("rate limited"), ClaudeAPIError("rate limited again")]
        )
        with pytest.raises(EvaluationGenerationFailedError):
            generate_evaluation(client, **self._kwargs())

    def test_does_not_attempt_a_third_call(self) -> None:
        client = MockClaudeClient(
            script=[
                ClaudeAPIError("rate limited"),
                ClaudeAPIError("rate limited again"),
                ClaudeResponse(content=json.dumps(_VALID_PAYLOAD)),
            ]
        )
        with pytest.raises(EvaluationGenerationFailedError):
            generate_evaluation(client, **self._kwargs())
        assert len(client.call_log) == 2
