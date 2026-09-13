"""Prompt template skeletons (spec MEADOWOPS-INFRA-003, PRD line 470:
"Prompt template skeletons drafted (generation, stakeholder roleplay,
evaluation)"; PRD 6.11: "Reusable/templated prompts; versioned prompts that
never silently rewrite history").

Drafted, not implemented - Phase 1 scaffolding for the three Claude-backed
flows Phase 3 builds out in full: scenario generation (U22, 6.4),
stakeholder persona roleplay (U23, 6.5/6.6), and draft evaluation (U25,
6.8). Actually calling Claude, validating its output, and driving the
pushback/retry loop are out of scope here - this module only owns the
reusable, versioned prompt text those units will render and send.

Files, not a table (unlike Unit 10's exception-rule thresholds): these are
Builder-authored and version-controlled via git, the same "who mutates it
and when" reasoning as DD-14/DD-15's KPI SQL. The later,
admin-editable/append-only concerns in PRD 6.9/6.11 (ER-6: prompts/
templates versioned; a `Scenario.prompt_version` foreign-key referrer) need
an `Evaluation` table to attach to, which does not exist yet - that
promotion happens at U25, not here.

Updated at Unit 18 (MEADOWOPS-DOM-011, DD-24 point 1): a real `Scenario`
row (app.db.scenario) now exists, earlier than this docstring originally
said ("at U22, not here") - the user's explicit choice, since U18 needed
a real table for its own Draft/Approved/Active/Cancelled lifecycle rather
than waiting for U22's AI-generation pipeline. Unit 18's own ground-truth
builder (app.domain.scenario.build_ground_truth_from_exception_flag) stayed
a separate, deterministic, non-AI path that populates the same seven-field
shape by hand/from a real ExceptionFlag instead.

Updated at Unit 22 (MEADOWOPS-DOM-016): GENERATION_TEMPLATE is now called,
by app.domain.scenario_generation.build_generation_prompt - rendered as-is
(this file stays untouched per PRD 6.11 ER-6's "versioned, never silently
rewritten"), with that module's own JSON-response-format instructions
appended as an unversioned suffix rather than folded into the template text
here.

Updated at Unit 23 (MEADOWOPS-DOM-017): STAKEHOLDER_ROLEPLAY_TEMPLATE is
now called, by app.domain.persona_chat.build_pushback_prompt - also
rendered as-is, with an attitude modifier appended as an unversioned suffix
rather than folded in, the same discipline. SUFFICIENCY_CHECK_TEMPLATE is
new at this unit (not a pre-existing skeleton like the other three) - its
own JSON-response-format instructions are part of the template text itself
here, since there is no prior frozen version to avoid disturbing.
"""

from __future__ import annotations

from dataclasses import dataclass


class PromptRenderError(ValueError):
    """Raised when a template is rendered without its full required context."""


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    version: str
    template: str
    required_context: frozenset[str]

    def render(self, context: dict[str, str]) -> str:
        missing = self.required_context - context.keys()
        if missing:
            raise PromptRenderError(
                f"{self.name} v{self.version} missing required context: "
                f"{sorted(missing)}"
            )
        # required_context only names the fields *this* template's caller must
        # supply; it isn't independently verified against the placeholders the
        # template text actually contains (a separate test does that for the
        # templates below). Re-raise any drift as PromptRenderError instead of
        # a bare KeyError/ValueError so the class's own contract holds even if
        # that invariant is ever broken.
        try:
            return self.template.format(**context)
        except (KeyError, ValueError) as exc:
            raise PromptRenderError(
                f"{self.name} v{self.version} template does not match its "
                f"required_context: {exc}"
            ) from exc


GENERATION_TEMPLATE = PromptTemplate(
    name="scenario_generation",
    version="v1",
    required_context=frozenset(
        {"scenario_type", "difficulty_tier", "competency_cluster", "evidence_package"}
    ),
    template=(
        "You are generating a supply-chain work scenario for an Analyst "
        "trainee, at difficulty tier {difficulty_tier}, of type "
        "{scenario_type}, targeting the {competency_cluster} competency "
        "cluster.\n\n"
        "Ground-truth evidence package (do not exceed or contradict this):\n"
        "{evidence_package}\n\n"
        "Trust-level every fact you introduce: Level 1 (Database Fact), "
        "Level 2 (Derived Fact), Level 3 (Stakeholder Statement), Level 4 "
        "(Stakeholder Belief, may be wrong). Never present a fabricated "
        "number as Level 1 or Level 2 - only numbers present in the "
        "evidence package above may carry those labels. Reference only "
        "product, supplier, warehouse, and order identifiers that exist in "
        "the evidence package; never invent an identifier.\n\n"
        "Produce the scenario as a Known Cause, Evidence, Supporting "
        "Signals, Distractors, Expected Considerations, Acceptable/"
        "Unacceptable Conclusions, and Uncertainty package."
    ),
)

STAKEHOLDER_ROLEPLAY_TEMPLATE = PromptTemplate(
    name="stakeholder_roleplay",
    version="v1",
    required_context=frozenset(
        {
            "persona_name",
            "persona_priorities",
            "persona_style",
            "known_information",
            "conversation_history",
            "analyst_message",
        }
    ),
    template=(
        "You are roleplaying {persona_name}, a stakeholder in a supply-"
        "chain scenario. Your priorities: {persona_priorities}. Your "
        "communication style: {persona_style}.\n\n"
        "You know only the following - do not reveal or reference anything "
        "outside it; this information asymmetry is intentional:\n"
        "{known_information}\n\n"
        "Conversation so far:\n{conversation_history}\n\n"
        "The Analyst just said:\n{analyst_message}\n\n"
        "Reply in character, as {persona_name} would, using only what "
        "{persona_name} knows."
    ),
)

SUFFICIENCY_CHECK_TEMPLATE = PromptTemplate(
    name="sufficiency_check",
    version="v1",
    required_context=frozenset({"ground_truth_package", "analyst_message"}),
    template=(
        "You are grading whether an Analyst trainee's latest message to a "
        "stakeholder is sufficient, against this scenario's ground truth "
        "(the Analyst never sees this):\n{ground_truth_package}\n\n"
        "The Analyst's latest message:\n{analyst_message}\n\n"
        "This is a recommendation only, distinct from a final evaluation - "
        "you never grade the Analyst's overall performance here, only "
        "whether this one message engages the evidence enough to move the "
        "conversation forward, or needs pushback first.\n\n"
        "Never state a specific ground-truth fact (a supporting signal, "
        "distractor, expected consideration, or conclusion) directly in "
        "suggested_pushback - a Builder may paste it straight into the "
        "thread the Analyst is meant to investigate independently. Phrase "
        "it only as a Socratic nudge that prompts further investigation.\n\n"
        "Respond with ONLY a single JSON object (no prose, no markdown "
        "fences) with exactly these keys: \"verdict\" (either \"sufficient\" "
        "or \"insufficient\") and \"suggested_pushback\" (a string with a "
        "suggested pushback message when verdict is \"insufficient\", or "
        "null when verdict is \"sufficient\")."
    ),
)

EVALUATION_TEMPLATE = PromptTemplate(
    name="draft_evaluation",
    version="v1",
    required_context=frozenset(
        {
            "ground_truth_package",
            "evidence_package",
            "stakeholder_context",
            "expected_cluster_behaviors",
            "analyst_responses",
            "outcome",
        }
    ),
    template=(
        "DRAFT - NOT AUTHORITATIVE. This evaluation is a draft input to "
        "human review, never the final word.\n\n"
        "Ground truth:\n{ground_truth_package}\n\n"
        "Evidence package:\n{evidence_package}\n\n"
        "Stakeholder context:\n{stakeholder_context}\n\n"
        "Expected cluster behaviors:\n{expected_cluster_behaviors}\n\n"
        "Analyst's responses:\n{analyst_responses}\n\n"
        "Outcome:\n{outcome}\n\n"
        "Produce a structured evaluation with exactly these sections: "
        "Strengths, Gaps, Evidence, Senior Analyst Pushback, Final "
        "Verdict, Suggested Next Skill Focus, and a Difficulty "
        "Recommendation per competency cluster. No single number is the "
        "sole representation of performance. Use only the evidence "
        "package above - you do not have access to the full database."
    ),
)

ALL_TEMPLATES = (
    GENERATION_TEMPLATE,
    STAKEHOLDER_ROLEPLAY_TEMPLATE,
    SUFFICIENCY_CHECK_TEMPLATE,
    EVALUATION_TEMPLATE,
)
