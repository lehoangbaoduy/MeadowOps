"""Unit 23 (MEADOWOPS-DOM-017, business id MEADOWOPS-DOMAIN-012, PRD 6.5/
6.6/6.13): pure domain-layer pieces for two Claude-backed persona-chat
features that hang off an existing chat thread - suggesting a pushback
message in a persona's voice, and an AI "is this message sufficient"
recommendation. Mirrors app.domain.scenario_generation's shape (Unit 22):
prompt building, response parsing, and the same exactly-one-automatic-retry
orchestration (PRD 9.2).

Scoping decisions made with the user 2026-09-05 (see DD-33):
- Attitude is a fixed preset list (this module's own Attitude enum), layered
  on top of a persona's fixed PRD 6.5 style as an unversioned suffix to
  STAKEHOLDER_ROLEPLAY_TEMPLATE's rendered text - the template itself
  (frozen v1) is never edited, the same ER-6 discipline Unit 22 established
  for GENERATION_TEMPLATE.
- known_information is a *redacted* projection of a scenario's ground_truth
  (known_cause + evidence only), never the full package. The other five
  ground_truth keys (supporting_signals, distractors, expected_
  considerations, acceptable_conclusions, unacceptable_conclusions,
  uncertainty) are the answer key U18/U22 wrote for grading - handing them
  to a persona the Analyst can talk to would let the Analyst extract the
  answer by chatting instead of investigating, defeating PRD 6.5's
  information-asymmetry intent. The sufficiency check is the opposite case:
  it grades against the ground truth, so it gets the full package,
  unredacted.
- AI-suggestion is pushback-only (PRD 6.6 steps 5-7), even though step 2's
  own text allows an AI-suggested opening message too - that variant needs
  a template shape with no prior analyst_message to react to, which is a
  real design question of its own, deferred rather than answered as a
  drive-by here. The opening message (step 2) stays Builder-typed only for
  now; STAKEHOLDER_ROLEPLAY_TEMPLATE's existing required `analyst_message`
  context is therefore always a real prior Analyst message.
- The sufficiency check's output is structured JSON (verdict +
  suggested_pushback), schema-validated the same way U22's narrative is.

No DB or session access here, the same layering app.domain.scenario_
generation's own docstring establishes: app.services.persona_chat is the
one module that knows about ChatThread/ChatMessage/Scenario and calls into
this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

from app.db.enums import StakeholderPersona
from app.domain.claude_client import ClaudeAPIError, ClaudeClient
from app.domain.prompt_templates import STAKEHOLDER_ROLEPLAY_TEMPLATE, SUFFICIENCY_CHECK_TEMPLATE

# Placeholder pending the real Anthropic SDK adapter (Phase 4, blocker B3) -
# see app.domain.scenario_generation's identical constant.
_CLAUDE_MODEL = "claude-sonnet-4-5"
_MAX_TOKENS = 1024
# PRD 9.2: exactly one automatic retry (the original call plus one retry).
_MAX_ATTEMPTS = 2

# Duplicated from app.domain.scenario_generation's own two-call retry loop
# rather than extracted into a shared helper - the two loops differ in their
# retryable-exception tuple and terminal exception type, and U22's code just
# cleared both reviewers, so this is not yet a real abstraction (a third
# occurrence, e.g. U25's evaluation pipeline, would be).


class PersonaMessageGenerationFailedError(Exception):
    """Raised once the one automatic retry (PRD 9.2) is exhausted while
    generating a persona pushback suggestion."""

    def __init__(self, last_error: Exception) -> None:
        self.last_error = last_error
        super().__init__(f"persona pushback suggestion failed after one retry: {last_error}")


class SufficiencyCheckSchemaError(ValueError):
    """Raised when the sufficiency check's response is not valid JSON, or is
    missing or mistypes a required key (PRD 9.2's "malformed/incomplete
    output" case)."""


class SufficiencyCheckFailedError(Exception):
    """Raised once the one automatic retry (PRD 9.2) is exhausted running
    the AI sufficiency check."""

    def __init__(self, last_error: Exception) -> None:
        self.last_error = last_error
        super().__init__(f"sufficiency check failed after one retry: {last_error}")


class Attitude(str, Enum):
    NEUTRAL = "neutral"
    FRUSTRATED = "frustrated"
    URGENT = "urgent"
    SKEPTICAL = "skeptical"
    APPRECIATIVE = "appreciative"


_ATTITUDE_DESCRIPTIONS: dict[Attitude, str] = {
    Attitude.NEUTRAL: "matter-of-fact, no strong emotion",
    Attitude.FRUSTRATED: "visibly frustrated and impatient",
    Attitude.URGENT: "conveying real time pressure, wants a fast answer",
    Attitude.SKEPTICAL: "doubtful, questioning the Analyst's claims",
    Attitude.APPRECIATIVE: "positive, appreciative of the Analyst's work so far",
}


@dataclass(frozen=True)
class PersonaProfile:
    name: str
    priorities: str
    style: str


# Transcribed directly from PRD 6.5's persona table - Builder-authored,
# version-controlled content, not an admin-editable entity, the same "who
# mutates it and when" reasoning as baseline_data.py's fixed catalog data
# and DD-14/DD-15's KPI SQL.
PERSONA_PROFILES: dict[StakeholderPersona, PersonaProfile] = {
    StakeholderPersona.OPERATIONS_MANAGER: PersonaProfile(
        name="Operations Manager",
        priorities="Service level, throughput, warehouse execution",
        style="Operational, concrete, impatient with abstraction",
    ),
    StakeholderPersona.PROCUREMENT_MANAGER: PersonaProfile(
        name="Procurement Manager",
        priorities="Price, supplier reliability, lead time, contract risk",
        style="Cost-focused, comparative",
    ),
    StakeholderPersona.WAREHOUSE_MANAGER: PersonaProfile(
        name="Warehouse Manager",
        priorities="Inventory accuracy, workload, practical execution",
        style="Operational, may resist workload-increasing changes",
    ),
    StakeholderPersona.IT_MANAGER: PersonaProfile(
        name="IT Manager",
        priorities="Data integrity, system behavior, feasibility, risk",
        style="Technical, scope-conscious",
    ),
    StakeholderPersona.OPERATIONS_DIRECTOR: PersonaProfile(
        name="Operations Director / VP",
        priorities="Business outcomes, service level, risk, decisions",
        style="Concise, outcome-focused",
    ),
    StakeholderPersona.CFO: PersonaProfile(
        name="CFO",
        priorities="Financial impact, cost, risk, measurable outcomes",
        style="Concise, financially oriented",
    ),
}

# The only two ground_truth keys that are world-state facts rather than
# grading content - see module docstring. Deliberately an allow-list (only
# these keys are ever copied out), not a deny-list of grading keys to
# exclude - an allow-list fails closed if a future unit adds a new
# ground_truth key.
_KNOWN_INFORMATION_KEYS = ("known_cause", "evidence")


@dataclass(frozen=True)
class SufficiencyVerdict:
    verdict: str
    suggested_pushback: str | None


def build_known_information(ground_truth: dict) -> dict:
    """Redacted projection of a scenario's ground_truth - see module
    docstring. Only known_cause and evidence ever reach a persona's prompt;
    the grading-only keys never do, regardless of what ground_truth
    contains."""
    return {key: ground_truth[key] for key in _KNOWN_INFORMATION_KEYS if key in ground_truth}


def build_pushback_prompt(
    *,
    persona: StakeholderPersona,
    attitude: Attitude,
    known_information: dict,
    conversation_history: str,
    analyst_message: str,
) -> str:
    profile = PERSONA_PROFILES[persona]
    rendered = STAKEHOLDER_ROLEPLAY_TEMPLATE.render(
        {
            "persona_name": profile.name,
            "persona_priorities": profile.priorities,
            "persona_style": profile.style,
            "known_information": json.dumps(known_information, sort_keys=True, default=str),
            "conversation_history": conversation_history,
            "analyst_message": analyst_message,
        }
    )
    return rendered + f"\n\nAdopt this attitude while replying: {_ATTITUDE_DESCRIPTIONS[attitude]}"


def suggest_pushback_message(
    client: ClaudeClient,
    *,
    persona: StakeholderPersona,
    attitude: Attitude,
    known_information: dict,
    conversation_history: str,
    analyst_message: str,
) -> str:
    """One automatic retry on a Claude API error/timeout or an empty
    response (PRD 9.2) - a second consecutive failure of either kind is
    surfaced as PersonaMessageGenerationFailedError. Free-form prose, not
    schema-validated - unlike the sufficiency check, this is just a chat
    message the Builder may edit or discard before sending."""
    prompt = build_pushback_prompt(
        persona=persona,
        attitude=attitude,
        known_information=known_information,
        conversation_history=conversation_history,
        analyst_message=analyst_message,
    )
    profile = PERSONA_PROFILES[persona]
    last_error: Exception | None = None
    for _attempt in range(_MAX_ATTEMPTS):
        try:
            response = client.create_message(
                model=_CLAUDE_MODEL,
                system=(
                    f"You roleplay {profile.name}, a stakeholder in a "
                    "supply-chain scenario. Reply in character, in plain "
                    "text - no JSON, no markdown."
                ),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=_MAX_TOKENS,
            )
            if response.content.strip():
                return response.content
            last_error = ClaudeAPIError("empty response content")
        except ClaudeAPIError as exc:
            last_error = exc
    assert last_error is not None  # every loop iteration above sets it on failure
    raise PersonaMessageGenerationFailedError(last_error)


def parse_sufficiency_response(content: str) -> SufficiencyVerdict:
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, RecursionError) as exc:
        # Security review precedent from Unit 22: json.loads on sufficiently
        # deeply-nested input raises RecursionError, not JSONDecodeError -
        # both are "malformed input" and fold into the same clean schema
        # error rather than an unhandled 500.
        raise SufficiencyCheckSchemaError(f"response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SufficiencyCheckSchemaError("response JSON must be an object")

    verdict = payload.get("verdict")
    if verdict not in ("sufficient", "insufficient"):
        raise SufficiencyCheckSchemaError('"verdict" must be "sufficient" or "insufficient"')

    suggested_pushback = payload.get("suggested_pushback")
    if suggested_pushback is not None and not isinstance(suggested_pushback, str):
        raise SufficiencyCheckSchemaError('"suggested_pushback" must be a string or null')
    if verdict == "insufficient" and not (
        isinstance(suggested_pushback, str) and suggested_pushback.strip()
    ):
        raise SufficiencyCheckSchemaError(
            '"suggested_pushback" must be a non-empty string when verdict is "insufficient"'
        )
    if verdict == "sufficient":
        suggested_pushback = None

    return SufficiencyVerdict(verdict=verdict, suggested_pushback=suggested_pushback)


def run_sufficiency_check(
    client: ClaudeClient, *, ground_truth: dict, analyst_message: str
) -> SufficiencyVerdict:
    """One automatic retry on a Claude API error/timeout or malformed/
    incomplete output (PRD 9.2) - a second consecutive failure of either
    kind is surfaced as SufficiencyCheckFailedError. Unlike the pushback
    suggestion, this call gets the *full* ground_truth package - it grades
    against it, it doesn't roleplay from it."""
    prompt = SUFFICIENCY_CHECK_TEMPLATE.render(
        {
            "ground_truth_package": json.dumps(ground_truth, sort_keys=True, default=str),
            "analyst_message": analyst_message,
        }
    )
    last_error: Exception | None = None
    for _attempt in range(_MAX_ATTEMPTS):
        try:
            response = client.create_message(
                model=_CLAUDE_MODEL,
                system=(
                    "You grade an Analyst trainee's message against ground "
                    "truth. You respond with JSON only, never prose."
                ),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=_MAX_TOKENS,
            )
            return parse_sufficiency_response(response.content)
        except (ClaudeAPIError, SufficiencyCheckSchemaError) as exc:
            last_error = exc
    assert last_error is not None  # every loop iteration above sets it on failure
    raise SufficiencyCheckFailedError(last_error)
