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
from dataclasses import dataclass

from app.domain.claude_client import ClaudeAPIError, ClaudeClient
from app.domain.prompt_templates import GENERATION_TEMPLATE

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
    "list empty if none)."
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


@dataclass(frozen=True)
class ScenarioNarrative:
    supporting_signals: list[str]
    distractors: list[str]
    expected_considerations: list[str]
    acceptable_conclusions: list[str]
    unacceptable_conclusions: list[str]
    uncertainty: str
    referenced_entity_ids: dict[str, list[str]]


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

    return ScenarioNarrative(
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
