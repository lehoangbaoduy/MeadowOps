"""Unit 25 (MEADOWOPS-DOM-019, business id MEADOWOPS-DOMAIN-014, PRD 6.6
steps 8-9, 6.7, 6.8): the transactional glue between app.domain.
evaluation/app.domain.difficulty_engine's pure logic and the real
`chat.chat_thread`/`chat.chat_message`/`engine.scenario`/`engine.
evaluation` tables - the same layering app.services.persona_chat
established for Unit 23.

`complete_thread_and_generate_evaluation` is the one function in this
module that writes anything, and it does both writes (ChatThread.status ->
COMPLETED, insert the Evaluation row) in the same transaction as the one
Claude call - if generation fails after its one automatic retry (PRD 9.2),
the whole call raises and neither write happens: the thread is NOT marked
Completed, and the Builder retries the whole action from where it left
off. This is a deliberate design choice (see app.db.enums.
ChatThreadStatus's own docstring) to avoid ever persisting a "stuck under
evaluation" state - PRD 6.1 names "Under AI Evaluation" as a state, but
nothing here needs to observe a thread sitting in it, since evaluation
either finishes inside this one call or the thread never left OPEN.

app.services.persona_chat's own security-review note about holding a DB
session open across a Claude call applies identically here - not
re-solved as a drive-by, same Phase-4-adapter constraint.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.chat import ChatMessage, ChatThread
from app.db.enums import (
    ChatThreadStatus,
    CompetencyCluster,
    DifficultyRecommendation,
    ScenarioStatus,
    UserRole,
)
from app.db.evaluation import Evaluation
from app.db.scenario import Scenario
from app.domain.claude_client import ClaudeClient
from app.domain.difficulty_engine import resolve_cluster_tier
from app.domain.evaluation import (
    EXPECTED_CLUSTER_BEHAVIORS,
    build_outcome,
    generate_evaluation,
)
from app.domain.persona_chat import PERSONA_PROFILES, build_known_information
from app.domain.prompt_templates import EVALUATION_TEMPLATE
from app.services.chat import get_thread, list_messages
from app.services.persona_chat import ScenarioCancelledError
from app.services.scenario_service import ScenarioNotFoundError

_PROMPT_VERSION = f"{EVALUATION_TEMPLATE.name}/{EVALUATION_TEMPLATE.version}"

# Ordered most-recent-first (matches app.domain.difficulty_engine.
# resolve_cluster_tier's own contract) and capped - a handful of recent
# evaluations is what "multiple relevant interactions" (PRD 6.7) means,
# not the cluster's entire history. Same magnitude as Unit 24's
# find_callback_candidates default limit. Deliberately larger than
# resolve_cluster_tier's own MINIMUM_OBSERVATIONS=2 (security review
# note) - headroom for that function to grow a longer trend window later
# without a second call site change here, not a bug; today it only ever
# consumes the first 2 of what's fetched.
_RECENT_RECOMMENDATIONS_LIMIT = 5


class ThreadAlreadyCompletedError(ValueError):
    """Raised when a thread has already been marked Completed - PRD 6.6
    step 8/9 is a single per-thread transition, not repeatable."""


class LatestMessageNotFromAnalystError(ValueError):
    """Raised when a thread has no messages yet, or its latest message is
    not from the Analyst - PRD 6.6 step 8: "the Analyst's most recent
    message is the submission of record", so there must be one to submit."""


def _analyst_responses_text(messages: list[ChatMessage]) -> str:
    """PRD 6.8: the evaluation is built from "the Analyst's responses" -
    the Analyst's own turns only, distinct from stakeholder_context (the
    persona's side of the conversation). Takes the thread's already-
    fetched message list (code review, LOW) rather than re-querying it -
    the caller already has it from its own latest-message check.

    Security review, LOW, documented not fixed - same as app.services.
    persona_chat._conversation_history_text's own note: no cap on how
    many Analyst messages accumulate here (each individual body is
    already bounded by MAX_MESSAGE_BODY_LENGTH, just not how many of
    them accumulate) - a token-growth/cost concern on a Builder-only
    route, not a security defect, and no PRD rule sets a round-count
    limit to enforce here."""
    return "\n".join(message.body for message in messages if message.sender_role == UserRole.ANALYST)


def complete_thread_and_generate_evaluation(
    session: Session, *, thread_id: uuid.UUID, claude_client: ClaudeClient
) -> Evaluation:
    thread = get_thread(session, thread_id)
    if thread.status == ChatThreadStatus.COMPLETED:
        raise ThreadAlreadyCompletedError(f"chat thread {thread_id} is already completed")

    messages = list_messages(session, thread_id)
    if not messages or messages[-1].sender_role != UserRole.ANALYST:
        raise LatestMessageNotFromAnalystError(
            f"chat thread {thread_id} has no Analyst message as its latest submission"
        )

    scenario = session.get(Scenario, thread.scenario_id)
    if scenario is None:
        # Unreachable via any route today - ChatThread.scenario_id is a
        # hard FK (app.db.chat's own docstring) and Scenario rows are
        # never deleted (app.db.scenario's own docstring) - kept as
        # defense in depth rather than a bare assert (code review
        # precedent: an assert is stripped under `python -O`, turning
        # this into an unhandled AttributeError on the next line instead
        # of a clean error), same pattern app.services.persona_chat.
        # _load_thread_and_active_scenario already establishes.
        raise ScenarioNotFoundError(f"scenario {thread.scenario_id} not found")
    if scenario.status == ScenarioStatus.CANCELLED:
        # advisor review, blocking: unlike app.services.persona_chat's
        # read-only Claude calls (where skipping this guard just wastes a
        # call), this function writes an Evaluation row the migration-0020
        # trigger makes permanently immutable - a cancelled scenario's
        # thread must never reach that write, since there's no way to
        # retract it afterward. Same guard/error class
        # _load_thread_and_active_scenario already established.
        raise ScenarioCancelledError(f"scenario {scenario.id} is cancelled")

    profile = PERSONA_PROFILES[thread.persona]
    result = generate_evaluation(
        claude_client,
        ground_truth_package=scenario.ground_truth,
        evidence_package=build_known_information(scenario.ground_truth),
        stakeholder_context=f"{profile.name} ({profile.priorities}; {profile.style})",
        expected_cluster_behaviors=EXPECTED_CLUSTER_BEHAVIORS[scenario.competency_cluster],
        analyst_responses=_analyst_responses_text(messages),
        outcome=build_outcome(scenario.ground_truth),
    )

    evaluation = Evaluation(
        thread_id=thread_id,
        prompt_version=_PROMPT_VERSION,
        strengths=result.strengths,
        gaps=result.gaps,
        evidence=result.evidence,
        senior_analyst_pushback=result.senior_analyst_pushback,
        final_verdict=result.final_verdict,
        suggested_next_skill_focus=result.suggested_next_skill_focus,
        difficulty_recommendation=result.difficulty_recommendation,
        raw_response=result.raw_response,
    )
    session.add(evaluation)
    thread.status = ChatThreadStatus.COMPLETED
    session.flush()
    return evaluation


def get_evaluation_for_thread(session: Session, thread_id: uuid.UUID) -> Evaluation | None:
    return session.scalar(select(Evaluation).where(Evaluation.thread_id == thread_id))


def resolve_difficulty_for_cluster(
    session: Session, cluster: CompetencyCluster
) -> DifficultyRecommendation:
    """Joins through ChatThread -> Scenario to find the evaluations whose
    scenario is tagged with this cluster, most recent first, then hands
    that history to the pure engine (app.domain.difficulty_engine) to
    resolve."""
    rows = session.scalars(
        select(Evaluation.difficulty_recommendation)
        .join(ChatThread, ChatThread.id == Evaluation.thread_id)
        .join(Scenario, Scenario.id == ChatThread.scenario_id)
        .where(Scenario.competency_cluster == cluster)
        .order_by(Evaluation.created_at.desc())
        .limit(_RECENT_RECOMMENDATIONS_LIMIT)
    ).all()
    return resolve_cluster_tier(list(rows))
