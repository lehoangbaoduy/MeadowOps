"""Unit 22 (MEADOWOPS-DOM-016, business id MEADOWOPS-DOMAIN-011, PRD 6.4):
the Claude scenario-narrative generation pipeline — prompt building, JSON
schema parsing, and the exactly-one-automatic-retry orchestration PRD 9.2's
edge case table requires ("Claude API error/timeout during generation ->
Retried once automatically; if it still fails, flagged to the Builder";
the same one-retry semantics extends to malformed/incomplete output).

Structured JSON, not free prose (the user's explicit choice, MEADOWOPS-DOM-
016): Claude's response must be schema-validated per field so the DB-fact
check in app.services.scenario_service (referenced entity ids actually
existing) can run mechanically, matching PRD 6.8's evaluator pattern.

No DB or session access here, same layering app.domain.scenario's own
docstring establishes: this module only knows about the ClaudeClient
Protocol and the narrative's own shape, never about `live.*` tables. The
referenced-entity-id *existence* check is therefore not here - it lives in
app.services.scenario_service, the only module in this project already
importing both the ORM models it needs to check against and this module's
ClaudeClient-calling functions.

GENERATION_TEMPLATE (app.domain.prompt_templates) is reused, not
reimplemented - it is deliberately left untouched (PRD 6.11 ER-6: prompts
are versioned, never silently rewritten) even though its own prose-oriented
instructions predate this unit's structured-JSON requirement; the JSON
response-format instructions below are appended as a separate, unversioned
suffix rather than folded into the template text itself.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

import sqlparse

from app.domain.claude_client import ClaudeAPIError, ClaudeClient
from app.domain.persona_chat import without_builder_only_keys
from app.domain.prompt_templates import (
    EXPECTED_QUERY_TEMPLATE,
    GENERATION_TEMPLATE,
    NARRATIVE_TEXT_TEMPLATE,
)
from app.domain.query_classifier import StatementType, split_statements, classify_statement

# Placeholder pending the real Anthropic SDK adapter (Phase 4, blocker B3) -
# MockClaudeClient logs but never validates this value, and no live call is
# made anywhere in this project yet.
_CLAUDE_MODEL = "claude-sonnet-4-5"
_MAX_TOKENS = 4096
# PRD 9.2: exactly one automatic retry (the original call plus one retry).
_MAX_ATTEMPTS = 2
# Security review: an unbounded list here turns into an unbounded number of
# validate_referenced_entity_ids DB round-trips downstream, and Claude has
# no other structural reason to need more than a handful of items per field.
_MAX_LIST_ITEMS = 50

# Unit 38 (MEADOWOPS-DOM-026): generous for a few paragraphs / a real analytic
# query, small enough that neither can be used to stuff the JSON column.
MAX_NARRATIVE_CHARS = 4000
MAX_EXPECTED_QUERY_CHARS = 4000

_LIST_FIELDS: tuple[str, ...] = (
    "supporting_signals",
    "distractors",
    "expected_considerations",
    "acceptable_conclusions",
    "unacceptable_conclusions",
)
_ENTITY_ID_KEYS: frozenset[str] = frozenset(
    {"product_ids", "warehouse_ids", "supplier_ids", "purchase_order_ids", "shipment_ids"}
)

_JSON_FORMAT_INSTRUCTIONS = (
    "\n\nRespond with ONLY a single JSON object (no prose, no markdown "
    "fences) with exactly these keys: \"supporting_signals\" (list of "
    "strings), \"distractors\" (list of strings), \"expected_considerations\" "
    "(list of strings), \"acceptable_conclusions\" (list of strings), "
    "\"unacceptable_conclusions\" (list of strings), \"uncertainty\" "
    "(a non-empty string), and \"referenced_entity_ids\" (an object with "
    "keys \"product_ids\", \"warehouse_ids\", \"supplier_ids\", "
    "\"purchase_order_ids\", \"shipment_ids\", each a list of the identifier "
    "strings this scenario actually references - omit a key or leave its "
    "list empty if none). Also include \"narrative\" (a string: a short "
    "plain-language account of what happened in this scenario, for the "
    "Builder, never shown to the Analyst) and \"expected_query\" (a string: "
    "exactly ONE read-only PostgreSQL SELECT statement that would let an "
    "Analyst find the answer, written against the sandbox schema, i.e. "
    "tables referenced as sandbox.<table_name>, never live.* - no INSERT, "
    "UPDATE, DELETE, DDL or second statement)."
)


class ScenarioNarrativeSchemaError(ValueError):
    """Raised when Claude's response is not valid JSON, or is missing or
    mistypes a required key (PRD 9.2's "malformed/incomplete output" case)."""


class ScenarioGenerationFailedError(Exception):
    """Raised once the one automatic retry (PRD 9.2) is exhausted, wrapping
    the last underlying failure (a ClaudeAPIError/ClaudeTimeoutError or a
    ScenarioNarrativeSchemaError) so the caller can report it without
    needing to know which of the two kinds occurred last.

    Code review + security review (2026-09-04): app.api.admin_scenarios
    forwards str(this exception) verbatim as an HTTP 502 detail today, which
    is harmless while `last_error` can only ever be MockClaudeClient-authored
    test text - but the real Anthropic adapter that lands in Phase 4 (blocker
    B3) must not let a raw upstream response body/headers reach `last_error`
    unredacted, since that string flows straight into a response the Builder
    sees."""

    def __init__(self, last_error: Exception) -> None:
        self.last_error = last_error
        super().__init__(f"scenario narrative generation failed after one retry: {last_error}")


def normalize_expected_query(value: str) -> str:
    """Unit 38: the Builder-only suggested query must be exactly one plain
    read statement - it is later executed against the sandbox by the
    Builder's "run" control, and a model (or a hand edit) must never be able
    to smuggle a write in behind it. Returns the trimmed statement without
    its trailing semicolon, or "" when blank (blank means "no query").
    Raises ScenarioNarrativeSchemaError (a ValueError, so pydantic turns it
    into a 422 field error) otherwise."""
    if len(value) > MAX_EXPECTED_QUERY_CHARS:
        raise ScenarioNarrativeSchemaError(
            f'"expected_query" must not exceed {MAX_EXPECTED_QUERY_CHARS} characters'
        )
    # Comment-only fragments (a model adding "-- note" after the semicolon)
    # are not statements.
    statements = [
        stmt
        for stmt in split_statements(value)
        if sqlparse.format(stmt, strip_comments=True).strip().strip(";").strip()
    ]
    if not statements:
        return ""
    if len(statements) > 1:
        raise ScenarioNarrativeSchemaError('"expected_query" must be a single statement')
    if classify_statement(statements[0]) is not StatementType.READ:
        raise ScenarioNarrativeSchemaError('"expected_query" must be a read-only SELECT')
    statement = statements[0].rstrip()
    without_comments = sqlparse.format(statement, strip_comments=True).strip()
    if without_comments.endswith(";"):
        # "SELECT 1; -- note": drop the semicolon and the comment after it.
        return without_comments[:-1].rstrip()
    return statement.rstrip(";").rstrip()


def normalize_narrative(value: str) -> str:
    if len(value) > MAX_NARRATIVE_CHARS:
        raise ScenarioNarrativeSchemaError(
            f'"narrative" must not exceed {MAX_NARRATIVE_CHARS} characters'
        )
    return value.strip()


@dataclass(frozen=True)
class ScenarioNarrative:
    supporting_signals: list[str]
    distractors: list[str]
    expected_considerations: list[str]
    acceptable_conclusions: list[str]
    unacceptable_conclusions: list[str]
    uncertainty: str
    referenced_entity_ids: dict[str, list[str]]
    # Unit 38: optional on the wire (an older/leaner response still parses)
    # but always present here, "" meaning "none".
    narrative: str = ""
    expected_query: str = ""


def build_generation_prompt(
    *, scenario_type: str, difficulty_tier: str, competency_cluster: str, evidence_package: dict
) -> str:
    rendered = GENERATION_TEMPLATE.render(
        {
            "scenario_type": scenario_type,
            "difficulty_tier": difficulty_tier,
            "competency_cluster": competency_cluster,
            "evidence_package": json.dumps(evidence_package, sort_keys=True, default=str),
        }
    )
    return rendered + _JSON_FORMAT_INSTRUCTIONS


def _require_string_list(payload: dict, field_name: str) -> list[str]:
    value = payload.get(field_name)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ScenarioNarrativeSchemaError(f'"{field_name}" must be a list of strings')
    if len(value) > _MAX_LIST_ITEMS:
        raise ScenarioNarrativeSchemaError(
            f'"{field_name}" must not exceed {_MAX_LIST_ITEMS} items (got {len(value)})'
        )
    return value


def _optional_string(payload: dict, field_name: str) -> str:
    value = payload.get(field_name, "")
    if not isinstance(value, str):
        raise ScenarioNarrativeSchemaError(f'"{field_name}" must be a string')
    return value


def parse_narrative_response(content: str) -> ScenarioNarrative:
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, RecursionError) as exc:
        # Security review: json.loads on a sufficiently deeply-nested
        # document (e.g. `"["*N + "]"*N`) raises RecursionError, not
        # JSONDecodeError - both are "malformed input", so both fold into
        # the same clean schema error rather than an unhandled 500.
        raise ScenarioNarrativeSchemaError(f"response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ScenarioNarrativeSchemaError("response JSON must be an object")

    list_fields = {field_name: _require_string_list(payload, field_name) for field_name in _LIST_FIELDS}

    uncertainty = payload.get("uncertainty")
    if not isinstance(uncertainty, str) or not uncertainty.strip():
        raise ScenarioNarrativeSchemaError('"uncertainty" must be a non-empty string')

    raw_entity_ids = payload.get("referenced_entity_ids", {})
    if not isinstance(raw_entity_ids, dict):
        raise ScenarioNarrativeSchemaError('"referenced_entity_ids" must be an object')
    referenced_entity_ids: dict[str, list[str]] = {}
    for key, value in raw_entity_ids.items():
        if key not in _ENTITY_ID_KEYS:
            raise ScenarioNarrativeSchemaError(
                f'"referenced_entity_ids.{key}" is not a recognized entity type'
            )
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ScenarioNarrativeSchemaError(
                f'"referenced_entity_ids.{key}" must be a list of strings'
            )
        if len(value) > _MAX_LIST_ITEMS:
            raise ScenarioNarrativeSchemaError(
                f'"referenced_entity_ids.{key}" must not exceed {_MAX_LIST_ITEMS} items '
                f"(got {len(value)})"
            )
        referenced_entity_ids[key] = value

    narrative = _optional_string(payload, "narrative")
    expected_query = _optional_string(payload, "expected_query")

    return ScenarioNarrative(
        narrative=normalize_narrative(narrative),
        expected_query=normalize_expected_query(expected_query),
        supporting_signals=list_fields["supporting_signals"],
        distractors=list_fields["distractors"],
        expected_considerations=list_fields["expected_considerations"],
        acceptable_conclusions=list_fields["acceptable_conclusions"],
        unacceptable_conclusions=list_fields["unacceptable_conclusions"],
        uncertainty=uncertainty,
        referenced_entity_ids=referenced_entity_ids,
    )


def generate_scenario_narrative(
    client: ClaudeClient,
    *,
    scenario_type: str,
    difficulty_tier: str,
    competency_cluster: str,
    evidence_package: dict,
) -> ScenarioNarrative:
    """One automatic retry on a Claude API error/timeout or malformed/
    incomplete schema output (PRD 9.2) - a second consecutive failure of
    either kind is surfaced to the Builder as ScenarioGenerationFailedError
    rather than retried again."""
    prompt = build_generation_prompt(
        scenario_type=scenario_type,
        difficulty_tier=difficulty_tier,
        competency_cluster=competency_cluster,
        evidence_package=evidence_package,
    )
    last_error: Exception | None = None
    for _attempt in range(_MAX_ATTEMPTS):
        try:
            response = client.create_message(
                model=_CLAUDE_MODEL,
                system=(
                    "You generate structured supply-chain training scenarios. "
                    "You respond with JSON only, never prose."
                ),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=_MAX_TOKENS,
            )
            return parse_narrative_response(response.content)
        except (ClaudeAPIError, ScenarioNarrativeSchemaError) as exc:
            last_error = exc
    assert last_error is not None  # every loop iteration above sets it on failure
    raise ScenarioGenerationFailedError(last_error)


_SMALL_MAX_TOKENS = 1024
_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*\n?(.*?)\n?```$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    match = _CODE_FENCE_RE.match(stripped)
    return match.group(1).strip() if match else stripped


def _rendered_facts(ground_truth: dict) -> str:
    # The old narrative/query are deliberately left out: a regenerate should
    # produce a fresh answer from the facts, not paraphrase what it replaces.
    return json.dumps(without_builder_only_keys(ground_truth), sort_keys=True, default=str)


def build_narrative_prompt(
    *, scenario_type: str, difficulty_tier: str, competency_cluster: str, ground_truth: dict
) -> str:
    return NARRATIVE_TEXT_TEMPLATE.render(
        {
            "scenario_type": scenario_type,
            "difficulty_tier": difficulty_tier,
            "competency_cluster": competency_cluster,
            "ground_truth_package": _rendered_facts(ground_truth),
        }
    )


def build_expected_query_prompt(
    *,
    scenario_type: str,
    difficulty_tier: str,
    competency_cluster: str,
    ground_truth: dict,
    schema_summary: str,
) -> str:
    return EXPECTED_QUERY_TEMPLATE.render(
        {
            "scenario_type": scenario_type,
            "difficulty_tier": difficulty_tier,
            "competency_cluster": competency_cluster,
            "ground_truth_package": _rendered_facts(ground_truth),
            "schema_summary": schema_summary,
        }
    )


def _generate_text_with_retry(
    client: ClaudeClient, *, system: str, prompt: str, parse: Callable[[str], str]
) -> str:
    """Same PRD 9.2 rule as generate_scenario_narrative: one automatic retry
    on an API error or an answer `parse` rejects, then surface the failure."""
    last_error: Exception | None = None
    for _attempt in range(_MAX_ATTEMPTS):
        try:
            response = client.create_message(
                model=_CLAUDE_MODEL,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=_SMALL_MAX_TOKENS,
            )
            return parse(response.content)
        except (ClaudeAPIError, ScenarioNarrativeSchemaError) as exc:
            last_error = exc
    assert last_error is not None
    raise ScenarioGenerationFailedError(last_error)


def _parse_narrative_text(content: str) -> str:
    text = normalize_narrative(_strip_code_fence(content))
    if not text:
        raise ScenarioNarrativeSchemaError("the narrative came back empty")
    return text


def _parse_expected_query(content: str) -> str:
    query = normalize_expected_query(_strip_code_fence(content))
    if not query:
        raise ScenarioNarrativeSchemaError("the expected query came back empty")
    return query


def generate_narrative_text(
    client: ClaudeClient,
    *,
    scenario_type: str,
    difficulty_tier: str,
    competency_cluster: str,
    ground_truth: dict,
) -> str:
    """Unit 39: a fresh Builder-only narrative from the scenario's facts."""
    return _generate_text_with_retry(
        client,
        system="You write concise, factual supply-chain scenario narratives. Plain text only.",
        prompt=build_narrative_prompt(
            scenario_type=scenario_type,
            difficulty_tier=difficulty_tier,
            competency_cluster=competency_cluster,
            ground_truth=ground_truth,
        ),
        parse=_parse_narrative_text,
    )


def generate_expected_query(
    client: ClaudeClient,
    *,
    scenario_type: str,
    difficulty_tier: str,
    competency_cluster: str,
    ground_truth: dict,
    schema_summary: str,
) -> str:
    """Unit 39: a fresh single read-only SELECT, validated exactly like one
    typed by hand (normalize_expected_query)."""
    return _generate_text_with_retry(
        client,
        system="You write a single PostgreSQL SELECT statement. SQL only, no prose.",
        prompt=build_expected_query_prompt(
            scenario_type=scenario_type,
            difficulty_tier=difficulty_tier,
            competency_cluster=competency_cluster,
            ground_truth=ground_truth,
            schema_summary=schema_summary,
        ),
        parse=_parse_expected_query,
    )
