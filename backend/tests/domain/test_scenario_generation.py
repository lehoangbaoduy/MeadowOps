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
    build_expected_query_prompt,
    build_generation_prompt,
    build_narrative_prompt,
    generate_expected_query,
    generate_narrative_text,
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

    def test_asks_for_a_narrative_and_a_single_select_expected_query(self) -> None:
        prompt = build_generation_prompt(
            scenario_type="data_quality_issue",
            difficulty_tier="standard",
            competency_cluster="analysis_diagnosis",
            evidence_package=_EVIDENCE_PACKAGE,
        )
        assert '"narrative"' in prompt
        assert '"expected_query"' in prompt
        assert "sandbox." in prompt  # the Analyst's tables live in the sandbox schema


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

    def test_parses_the_narrative_and_expected_query(self) -> None:
        payload = {
            **_VALID_PAYLOAD,
            "narrative": "  Stock of SKU-COR-001 at WH-EAST fell below its cover threshold.  ",
            "expected_query": "SELECT * FROM sandbox.inventory_snapshot WHERE product_id = 'SKU-COR-001';",
        }

        narrative = parse_narrative_response(json.dumps(payload))

        assert narrative.narrative == "Stock of SKU-COR-001 at WH-EAST fell below its cover threshold."
        assert narrative.expected_query == (
            "SELECT * FROM sandbox.inventory_snapshot WHERE product_id = 'SKU-COR-001'"
        )

    def test_narrative_and_expected_query_default_to_empty_when_omitted(self) -> None:
        narrative = parse_narrative_response(json.dumps(_VALID_PAYLOAD))

        assert narrative.narrative == ""
        assert narrative.expected_query == ""

    @pytest.mark.parametrize("field_name", ["narrative", "expected_query"])
    def test_raises_when_narrative_or_expected_query_is_not_a_string(self, field_name: str) -> None:
        payload = {**_VALID_PAYLOAD, field_name: ["not", "a", "string"]}
        with pytest.raises(ScenarioNarrativeSchemaError):
            parse_narrative_response(json.dumps(payload))

    @pytest.mark.parametrize(
        "bad_query",
        [
            "DELETE FROM sandbox.product",
            "UPDATE sandbox.product SET name = 'x'",
            "DROP TABLE sandbox.product",
            "SELECT 1; DELETE FROM sandbox.product",
            "SELECT 1; SELECT 2",
            "WITH gone AS (DELETE FROM sandbox.product RETURNING *) SELECT * FROM gone",
            "SELECT * INTO sandbox.copy FROM sandbox.product",
        ],
    )
    def test_raises_when_expected_query_is_not_a_single_read_statement(self, bad_query: str) -> None:
        payload = {**_VALID_PAYLOAD, "expected_query": bad_query}
        with pytest.raises(ScenarioNarrativeSchemaError):
            parse_narrative_response(json.dumps(payload))

    @pytest.mark.parametrize(
        "query,expected",
        [
            ("SELECT 1; -- why this works", "SELECT 1"),
            ("SELECT 1;\n/* trailing note */", "SELECT 1"),
            ("-- nothing to run", ""),
            ("/* nothing to run */", ""),
        ],
    )
    def test_comment_only_fragments_do_not_count_as_extra_statements(
        self, query: str, expected: str
    ) -> None:
        # Unit 38 review: a model that appends a comment after the semicolon
        # must not make the whole generation fail.
        payload = {**_VALID_PAYLOAD, "expected_query": query}
        assert parse_narrative_response(json.dumps(payload)).expected_query == expected

    def test_raises_when_the_narrative_or_query_exceeds_the_length_cap(self) -> None:
        for field_name in ("narrative", "expected_query"):
            payload = {**_VALID_PAYLOAD, field_name: "SELECT 1 -- " + "x" * 10_000}
            with pytest.raises(ScenarioNarrativeSchemaError):
                parse_narrative_response(json.dumps(payload))

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


_GROUND_TRUTH = {
    "known_cause": "Reorder point misconfigured at WH-EAST",
    "evidence": {"product_id": "SKU-COR-001", "warehouse_id": "WH-EAST", "measured_value": "4.00"},
    "supporting_signals": ["stock fell below cover"],
    "distractors": ["a promotion last week"],
    "narrative": "OLD-NARRATIVE-MARKER",
    "expected_query": "SELECT 'OLD-QUERY-MARKER'",
}
_SCHEMA_SUMMARY = "sandbox.inventory_snapshot(product_id text, warehouse_id text, quantity_on_hand integer)"


class TestNarrativeAndQueryPrompts:
    def test_the_narrative_prompt_carries_the_facts_but_not_the_old_builder_notes(self) -> None:
        prompt = build_narrative_prompt(
            scenario_type="data_quality_issue",
            difficulty_tier="standard",
            competency_cluster="analysis_diagnosis",
            ground_truth=_GROUND_TRUTH,
        )
        assert "Reorder point misconfigured" in prompt
        assert "SKU-COR-001" in prompt
        assert "OLD-NARRATIVE-MARKER" not in prompt
        assert "OLD-QUERY-MARKER" not in prompt

    def test_the_query_prompt_includes_the_sandbox_schema_and_asks_for_one_select(self) -> None:
        prompt = build_expected_query_prompt(
            scenario_type="data_quality_issue",
            difficulty_tier="standard",
            competency_cluster="analysis_diagnosis",
            ground_truth=_GROUND_TRUTH,
            schema_summary=_SCHEMA_SUMMARY,
        )
        assert "sandbox.inventory_snapshot" in prompt
        assert "SELECT" in prompt
        assert "OLD-QUERY-MARKER" not in prompt


def _client(*contents: str | Exception) -> MockClaudeClient:
    return MockClaudeClient(
        script=[c if isinstance(c, Exception) else ClaudeResponse(content=c) for c in contents]
    )


def _generate_query(client: MockClaudeClient) -> str:
    return generate_expected_query(
        client,
        scenario_type="data_quality_issue",
        difficulty_tier="standard",
        competency_cluster="analysis_diagnosis",
        ground_truth=_GROUND_TRUTH,
        schema_summary=_SCHEMA_SUMMARY,
    )


def _generate_narrative(client: MockClaudeClient) -> str:
    return generate_narrative_text(
        client,
        scenario_type="data_quality_issue",
        difficulty_tier="standard",
        competency_cluster="analysis_diagnosis",
        ground_truth=_GROUND_TRUTH,
    )


class TestGenerateExpectedQuery:
    def test_returns_the_single_select_without_fences_or_trailing_semicolon(self) -> None:
        client = _client("```sql\nSELECT product_id FROM sandbox.inventory_snapshot;\n```")
        assert _generate_query(client) == "SELECT product_id FROM sandbox.inventory_snapshot"

    def test_retries_once_when_the_first_answer_is_not_a_read_only_select(self) -> None:
        client = _client("DELETE FROM sandbox.product", "SELECT 1")
        assert _generate_query(client) == "SELECT 1"
        assert len(client.call_log) == 2

    def test_retries_once_after_an_api_error(self) -> None:
        client = _client(ClaudeAPIError("overloaded"), "SELECT 1")
        assert _generate_query(client) == "SELECT 1"

    def test_fails_after_the_one_retry_is_used_up(self) -> None:
        client = _client("DELETE FROM sandbox.product", "UPDATE sandbox.product SET x = 1")
        with pytest.raises(ScenarioGenerationFailedError):
            _generate_query(client)
        assert len(client.call_log) == 2

    def test_an_empty_answer_counts_as_a_failure(self) -> None:
        client = _client("   ", "")
        with pytest.raises(ScenarioGenerationFailedError):
            _generate_query(client)


class TestGenerateNarrativeText:
    def test_returns_the_trimmed_text(self) -> None:
        assert _generate_narrative(_client("  Stock fell at WH-EAST.  \n")) == "Stock fell at WH-EAST."

    def test_retries_once_on_an_empty_answer_then_succeeds(self) -> None:
        client = _client("", "Stock fell at WH-EAST.")
        assert _generate_narrative(client) == "Stock fell at WH-EAST."
        assert len(client.call_log) == 2

    def test_fails_after_the_one_retry_is_used_up(self) -> None:
        with pytest.raises(ScenarioGenerationFailedError):
            _generate_narrative(_client(ClaudeAPIError("down"), ClaudeAPIError("down")))

    def test_an_over_long_answer_counts_as_a_failure(self) -> None:
        too_long = "x" * 5000
        with pytest.raises(ScenarioGenerationFailedError):
            _generate_narrative(_client(too_long, too_long))
