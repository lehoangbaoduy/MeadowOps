"""Unit 26 (MEADOWOPS-DOM-020, business id MEADOWOPS-DOMAIN-015, PRD 6.10):
the transactional layer over `engine.portfolio_artifact`, plus the
compiled-export read path that assembles PRD 6.10's full document from
`engine.scenario`/`chat.chat_message`/`engine.evaluation`/
`engine.human_review` without storing a second copy of any of it - see
app.db.portfolio's own docstring for why.

Does not commit - caller-owns-the-transaction, same convention as every
other service module in this project.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import ChatThreadStatus
from app.db.evaluation import Evaluation
from app.db.portfolio import PortfolioArtifact
from app.db.scenario import Scenario
from app.domain.portfolio import build_portfolio_export
from app.services.chat import get_thread, list_messages
from app.services.human_review import get_human_review_for_evaluation

MAX_REFLECTION_ANSWER_LENGTH = 5_000


class ThreadNotCompletedError(ValueError):
    """Raised when a reflection is being authored, or an export compiled,
    for a thread that hasn't reached ChatThreadStatus.COMPLETED yet - PRD
    6.10 compiles "per scenario" from its finished record, and the
    Analyst's own retrospective answers ("what changed after pushback")
    presuppose the scenario actually ran its course."""


class PortfolioArtifactAlreadyExistsError(ValueError):
    """Raised when a thread already has a reflection - PRD 6.10's
    seven-question reflection is authored once per scenario, not
    repeatable (same one-per-parent shape as Evaluation itself)."""


class ScenarioNotFoundError(ValueError):
    """Unreachable via any route today - ChatThread.scenario_id is a hard
    FK and Scenario rows are never deleted (app.services.evaluation's own
    identical precedent) - kept as defense in depth, not a bare assert."""


class EvaluationMissingForCompletedThreadError(ValueError):
    """Unreachable via any route today - complete_thread_and_generate_
    evaluation (Unit 25) writes the Evaluation row in the same transaction
    that sets ChatThreadStatus.COMPLETED, so a completed thread always has
    one. Kept as defense in depth rather than an unhandled AttributeError
    two lines later if that invariant is ever broken."""


def create_portfolio_reflection(
    session: Session,
    *,
    thread_id: uuid.UUID,
    submitted_by_user_id: uuid.UUID,
    reflection_what_happened: str,
    reflection_initial_thought: str,
    reflection_evidence_that_mattered: str,
    reflection_what_missed: str,
    reflection_what_changed_after_pushback: str,
    reflection_what_differently: str,
    reflection_skill_improved: str,
) -> PortfolioArtifact:
    thread = get_thread(session, thread_id)
    if thread.status != ChatThreadStatus.COMPLETED:
        raise ThreadNotCompletedError(f"chat thread {thread_id} is not yet completed")
    existing = session.scalar(
        select(PortfolioArtifact).where(PortfolioArtifact.thread_id == thread_id)
    )
    if existing is not None:
        raise PortfolioArtifactAlreadyExistsError(
            f"chat thread {thread_id} already has a portfolio reflection"
        )
    artifact = PortfolioArtifact(
        thread_id=thread_id,
        submitted_by_user_id=submitted_by_user_id,
        reflection_what_happened=reflection_what_happened,
        reflection_initial_thought=reflection_initial_thought,
        reflection_evidence_that_mattered=reflection_evidence_that_mattered,
        reflection_what_missed=reflection_what_missed,
        reflection_what_changed_after_pushback=reflection_what_changed_after_pushback,
        reflection_what_differently=reflection_what_differently,
        reflection_skill_improved=reflection_skill_improved,
    )
    session.add(artifact)
    session.flush()
    return artifact


def get_portfolio_artifact_for_thread(
    session: Session, thread_id: uuid.UUID
) -> PortfolioArtifact | None:
    return session.scalar(select(PortfolioArtifact).where(PortfolioArtifact.thread_id == thread_id))


def _evaluation_export_fields(evaluation: Evaluation) -> dict:
    # Same exclusion as app.schemas.evaluation.EvaluationRead - raw_response
    # never leaves this process on any route, including this compiled
    # export.
    return {
        "id": str(evaluation.id),
        "prompt_version": evaluation.prompt_version,
        "strengths": evaluation.strengths,
        "gaps": evaluation.gaps,
        "evidence": evaluation.evidence,
        "senior_analyst_pushback": evaluation.senior_analyst_pushback,
        "final_verdict": evaluation.final_verdict,
        "suggested_next_skill_focus": evaluation.suggested_next_skill_focus,
        "difficulty_recommendation": evaluation.difficulty_recommendation.value,
        "created_at": evaluation.created_at.isoformat(),
    }


def _human_review_export_fields(review) -> dict:
    return {
        "reviewer_name": review.reviewer_name,
        "verdict": review.verdict.value,
        "tier_assessment_notes": review.tier_assessment_notes,
        "overridden_recommendation": (
            review.overridden_recommendation.value
            if review.overridden_recommendation is not None
            else None
        ),
        "created_at": review.created_at.isoformat(),
    }


def _reflection_export_fields(artifact: PortfolioArtifact) -> dict:
    return {
        "reflection_what_happened": artifact.reflection_what_happened,
        "reflection_initial_thought": artifact.reflection_initial_thought,
        "reflection_evidence_that_mattered": artifact.reflection_evidence_that_mattered,
        "reflection_what_missed": artifact.reflection_what_missed,
        "reflection_what_changed_after_pushback": artifact.reflection_what_changed_after_pushback,
        "reflection_what_differently": artifact.reflection_what_differently,
        "reflection_skill_improved": artifact.reflection_skill_improved,
        "created_at": artifact.created_at.isoformat(),
    }


def get_portfolio_export(session: Session, thread_id: uuid.UUID) -> dict:
    thread = get_thread(session, thread_id)
    if thread.status != ChatThreadStatus.COMPLETED:
        raise ThreadNotCompletedError(f"chat thread {thread_id} is not yet completed")
    scenario = session.get(Scenario, thread.scenario_id)
    if scenario is None:
        raise ScenarioNotFoundError(f"scenario {thread.scenario_id} not found")
    evaluation = session.scalar(select(Evaluation).where(Evaluation.thread_id == thread_id))
    if evaluation is None:
        raise EvaluationMissingForCompletedThreadError(
            f"chat thread {thread_id} is completed but has no evaluation"
        )
    human_review = get_human_review_for_evaluation(session, evaluation.id)
    reflection = get_portfolio_artifact_for_thread(session, thread_id)
    messages = [
        {
            "sender_role": message.sender_role.value,
            "body": message.body,
            "sent_at": message.sent_at.isoformat(),
        }
        for message in list_messages(session, thread_id)
    ]
    return build_portfolio_export(
        scenario_title=scenario.title,
        scenario_type=scenario.scenario_type.value,
        competency_cluster=scenario.competency_cluster.value,
        messages=messages,
        evaluation=_evaluation_export_fields(evaluation),
        human_review=_human_review_export_fields(human_review) if human_review else None,
        reflection=_reflection_export_fields(reflection) if reflection else None,
    )
