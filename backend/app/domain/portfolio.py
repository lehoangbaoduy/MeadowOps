"""Unit 26 (MEADOWOPS-DOM-020, business id MEADOWOPS-DOMAIN-015, PRD 6.10):
pure assembly of the compiled portfolio export document. No DB access, no
Claude call - app.services.portfolio does the fetching, this module only
shapes what was fetched into the document PRD 6.10 describes: "trigger,
responses, pushback rounds, draft evaluation, reviewer notes, and a
7-question reflection".

Deliberately takes plain dicts/primitives, not ORM instances - the same
domain/service split app.domain.evaluation already established
(app.services.evaluation converts ORM rows to plain kwargs before calling
into the domain layer), so this function is unit-testable with no database
at all.
"""

from __future__ import annotations


def build_portfolio_export(
    *,
    scenario_title: str,
    scenario_type: str,
    competency_cluster: str,
    messages: list[dict],
    evaluation: dict,
    human_review: dict | None,
    reflection: dict | None,
) -> dict:
    """`messages` must already be ordered oldest-first (app.services.chat.
    list_messages's own contract) - PRD 6.6 step 2's opening chat message is
    the scenario's "trigger", so it's just `messages[0]` here rather than a
    second, separately-fetched value. `human_review`/`reflection` are both
    legitimately absent (PRD 1.6: neither a completed monthly review nor
    portfolio content is required for Done) - the export must still
    compile, with those two sections simply null, not raise or 404."""
    return {
        "scenario": {
            "title": scenario_title,
            "scenario_type": scenario_type,
            "competency_cluster": competency_cluster,
        },
        "trigger": messages[0]["body"] if messages else None,
        "messages": messages,
        "evaluation": evaluation,
        "human_review": human_review,
        "reflection": reflection,
    }
