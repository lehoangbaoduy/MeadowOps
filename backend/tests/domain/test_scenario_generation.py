"""Unit 22 (MEADOWOPS-DOM-016, business id MEADOWOPS-DOMAIN-011, PRD 6.4/
9.2): pure domain-layer tests for the Claude scenario-narrative generation
pipeline — prompt building, JSON schema parsing, and the exactly-one-
automatic-retry orchestration (PRD 9.2's edge case table: a Claude API
error/timeout or malformed/incomplete output gets one retry; a second
consecutive failure is surfaced to the Builder). No DB access here — see
app.domain.scenario_generation's own docstring for why the referenced-
entity-id *existence* check lives in app.services.scenario_service instead.
"""

from __future__ import annotations

import json

import pytest

from app.domain.claude_client import ClaudeAPIError, ClaudeResponse, ClaudeTimeoutError, MockClaudeClient
from app.domain.scenario_generation import (
    ScenarioGenerationFailedError,
    ScenarioNarrative,
    ScenarioNarrativeSchemaError,
    build_generation_prompt,
    generate_scenario_narrative,
    parse_narrative_response,
)

_VALID_PAYLOAD = {
    "supporting_signals": ["signal"],
    "distractors": ["distractor"],
    "expected_considerations": ["consideration"],
    "acceptable_conclusions": ["ok"],
    "unacceptable_conclusions": ["bad"],
    "uncertainty": "moderate",
    "referenced_entity_ids": {"product_ids": ["SKU-COR-001"], "warehouse_ids": ["WH-EAST"]},
}

_EVIDENCE_PACKAGE = {
    "source_exception_flag_id": "11111111-1111-1111-1111-111111111111",
    "category": "low_stock_days_of_supply",
    "product_id": "SKU-COR-001",
}

_LIST_FIELDS = (
    "supporting_signals",
    "distractors",
    "expected_considerations",
    "acceptable_conclusions",
    "unacceptable_conclusions",
)


class TestBuildGenerationPrompt:
    def test_includes_scenario_metadata_and_evidence(self) -> None:
        prompt = build_generation_prompt(
            scenario_type="data_quality_issue",
            difficulty_tier="standard",
            competency_cluster="analysis_diagnosis",
            evidence_package=_EVIDENCE_PACKAGE,
        )
        assert "data_quality_issue" in prompt
        assert "standard" in prompt
        assert "analysis_diagnosis" in prompt
        assert "SKU-COR-001" in prompt

    def test_instructs_a_json_only_response_naming_every_key(self) -> None:
        prompt = build_generation_prompt(
            scenario_type="data_quality_issue",
            difficulty_tier="standard",
            competency_cluster="analysis_diagnosis",
            evidence_package=_EVIDENCE_PACKAGE,
        )
        assert "JSON" in prompt
        for field_name in (*_LIST_FIELDS, "uncertainty", "referenced_entity_ids"):
            assert field_name in prompt


class TestParseNarrativeResponse:
    def test_parses_a_well_formed_payload(self) -> None:
        narrative = parse_narrative_response(json.dumps(_VALID_PAYLOAD))

        assert isinstance(narrative, ScenarioNarrative)
        assert narrative.supporting_signals == ["signal"]
        assert narrative.uncertainty == "moderate"
        assert narrative.referenced_entity_ids == {
            "product_ids": ["SKU-COR-001"],
            "warehouse_ids": ["WH-EAST"],
        }

    def test_defaults_referenced_entity_ids_to_empty_when_omitted(self) -> None:
        payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "referenced_entity_ids"}

        narrative = parse_narrative_response(json.dumps(payload))

        assert narrative.referenced_entity_ids == {}

    def test_raises_on_invalid_json(self) -> None:
        with pytest.raises(ScenarioNarrativeSchemaError):
            parse_narrative_response("not json at all")

    def test_raises_a_schema_error_not_a_recursion_error_on_deeply_nested_json(self) -> None:
        # Security review: json.loads on sufficiently deeply-nested input
        # raises RecursionError, not JSONDecodeError - both must fold into
        # the same clean schema error rather than an unhandled crash.
        deeply_nested = "[" * 3000 + "]" * 3000
        with pytest.raises(ScenarioNarrativeSchemaError):
            parse_narrative_response(deeply_nested)

    @pytest.mark.parametrize("field_name", _LIST_FIELDS)
    def test_raises_when_a_list_field_exceeds_the_item_cap(self, field_name: str) -> None:
        payload = {**_VALID_PAYLOAD, field_name: [f"item-{i}" for i in range(51)]}
        with pytest.raises(ScenarioNarrativeSchemaError):
            parse_narrative_response(json.dumps(payload))

    def test_raises_when_a_referenced_entity_id_list_exceeds_the_item_cap(self) -> None:
        payload = {
            **_VALID_PAYLOAD,
            "referenced_entity_ids": {"product_ids": [f"SKU-{i}" for i in range(51)]},
        }
        with pytest.raises(ScenarioNarrativeSchemaError):
            parse_narrative_response(json.dumps(payload))

    def test_raises_when_response_is_a_json_array_not_object(self) -> None:
        with pytest.raises(ScenarioNarrativeSchemaError):
            parse_narrative_response("[1, 2, 3]")

    @pytest.mark.parametrize("field_name", _LIST_FIELDS)
    def test_raises_when_a_required_list_field_is_missing(self, field_name: str) -> None:
        payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != field_name}
        with pytest.raises(ScenarioNarrativeSchemaError):
            parse_narrative_response(json.dumps(payload))

    @pytest.mark.parametrize("field_name", _LIST_FIELDS)
    def test_raises_when_a_required_list_field_is_the_wrong_type(self, field_name: str) -> None:
        payload = {**_VALID_PAYLOAD, field_name: "not a list"}
        with pytest.raises(ScenarioNarrativeSchemaError):
            parse_narrative_response(json.dumps(payload))

    @pytest.mark.parametrize("field_name", _LIST_FIELDS)
    def test_raises_when_a_list_field_contains_a_non_string(self, field_name: str) -> None:
        payload = {**_VALID_PAYLOAD, field_name: ["ok", 123]}
        with pytest.raises(ScenarioNarrativeSchemaError):
            parse_narrative_response(json.dumps(payload))

    def test_raises_when_uncertainty_is_missing(self) -> None:
        payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "uncertainty"}
        with pytest.raises(ScenarioNarrativeSchemaError):
            parse_narrative_response(json.dumps(payload))

    def test_raises_when_uncertainty_is_blank(self) -> None:
        payload = {**_VALID_PAYLOAD, "uncertainty": "   "}
        with pytest.raises(ScenarioNarrativeSchemaError):
            parse_narrative_response(json.dumps(payload))

    def test_raises_when_referenced_entity_ids_is_not_an_object(self) -> None:
        payload = {**_VALID_PAYLOAD, "referenced_entity_ids": ["not", "a", "dict"]}
        with pytest.raises(ScenarioNarrativeSchemaError):
            parse_narrative_response(json.dumps(payload))

    def test_raises_on_an_unrecognized_entity_id_key(self) -> None:
        payload = {**_VALID_PAYLOAD, "referenced_entity_ids": {"made_up_ids": ["x"]}}
        with pytest.raises(ScenarioNarrativeSchemaError):
            parse_narrative_response(json.dumps(payload))

    def test_raises_when_an_entity_id_list_contains_a_non_string(self) -> None:
        payload = {**_VALID_PAYLOAD, "referenced_entity_ids": {"product_ids": [123]}}
        with pytest.raises(ScenarioNarrativeSchemaError):
            parse_narrative_response(json.dumps(payload))


class TestGenerateScenarioNarrative:
    def _kwargs(self) -> dict:
        return dict(
            scenario_type="data_quality_issue",
            difficulty_tier="standard",
            competency_cluster="analysis_diagnosis",
            evidence_package=_EVIDENCE_PACKAGE,
        )

    def test_succeeds_on_the_first_call(self) -> None:
        client = MockClaudeClient(script=[ClaudeResponse(content=json.dumps(_VALID_PAYLOAD))])

        narrative = generate_scenario_narrative(client, **self._kwargs())

        assert narrative.uncertainty == "moderate"
        assert len(client.call_log) == 1

    def test_retries_once_after_a_claude_api_error_then_succeeds(self) -> None:
        client = MockClaudeClient(
            script=[
                ClaudeAPIError("rate limited"),
                ClaudeResponse(content=json.dumps(_VALID_PAYLOAD)),
            ]
        )

        narrative = generate_scenario_narrative(client, **self._kwargs())

        assert narrative.uncertainty == "moderate"
        assert len(client.call_log) == 2

    def test_retries_once_after_a_timeout_then_succeeds(self) -> None:
        client = MockClaudeClient(
            script=[
                ClaudeTimeoutError("timed out"),
                ClaudeResponse(content=json.dumps(_VALID_PAYLOAD)),
            ]
        )

        narrative = generate_scenario_narrative(client, **self._kwargs())

        assert len(client.call_log) == 2
        assert narrative is not None

    def test_retries_once_after_malformed_output_then_succeeds(self) -> None:
        client = MockClaudeClient(
            script=[
                ClaudeResponse(content="not json"),
                ClaudeResponse(content=json.dumps(_VALID_PAYLOAD)),
            ]
        )

        narrative = generate_scenario_narrative(client, **self._kwargs())

        assert len(client.call_log) == 2
        assert narrative.uncertainty == "moderate"

    def test_raises_after_the_retry_is_also_exhausted_on_api_errors(self) -> None:
        client = MockClaudeClient(
            script=[ClaudeAPIError("rate limited"), ClaudeAPIError("rate limited again")]
        )

        with pytest.raises(ScenarioGenerationFailedError):
            generate_scenario_narrative(client, **self._kwargs())
        assert len(client.call_log) == 2

    def test_raises_after_two_consecutive_malformed_outputs(self) -> None:
        client = MockClaudeClient(
            script=[
                ClaudeResponse(content="not json"),
                ClaudeResponse(content="still not json"),
            ]
        )

        with pytest.raises(ScenarioGenerationFailedError):
            generate_scenario_narrative(client, **self._kwargs())
        assert len(client.call_log) == 2

    def test_does_not_attempt_a_third_call(self) -> None:
        # Three failures queued; only two calls (the original + one retry)
        # should ever be made — a third queued success must go unused.
        client = MockClaudeClient(
            script=[
                ClaudeAPIError("1"),
                ClaudeAPIError("2"),
                ClaudeResponse(content=json.dumps(_VALID_PAYLOAD)),
            ]
        )

        with pytest.raises(ScenarioGenerationFailedError):
            generate_scenario_narrative(client, **self._kwargs())
        assert len(client.call_log) == 2
