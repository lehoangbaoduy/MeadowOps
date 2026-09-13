"""Unit 23 (MEADOWOPS-DOM-017, business id MEADOWOPS-DOMAIN-012, PRD 6.5/
6.6/6.13): the transactional glue between app.domain.persona_chat's pure
logic and the real `chat.chat_thread`/`chat.chat_message`/`engine.scenario`
tables - the one module in this project already importing both the chat ORM
models and Scenario, the same layering app.services.scenario_service
established for app.domain.scenario_generation's ClaudeClient-calling
functions.

Both public functions here are read-only - neither writes to the database
(no `session.add`, no status change, no message insert) or commits.
Suggesting a pushback message is not the same as sending one (PRD 6.6 step
5: the Builder "composes and sends" - the AI only ever suggests what a
Builder may edit or discard), and the sufficiency check is explicitly "a
recommendation only" (PRD 6.13) that "never writes an evaluation record
itself."

Both require at least one prior Analyst message in the thread - the
pushback suggestion because STAKEHOLDER_ROLEPLAY_TEMPLATE's required
`analyst_message` context needs a real message to react to (this is what
makes "pushback-only, not opening-message" enforceable in code, not just in
the UI), and the sufficiency check because PRD 6.13 defines it as reviewing
"the Analyst's latest message" - there is nothing to review before one
exists. Both also refuse to run against a cancelled scenario (Scenario.
status has no Analyst-facing meaning once cancelled, and continuing the
persona conversation past that point serves no purpose) - draft/approved/
active scenarios are all otherwise allowed, since nothing else in this
codebase's chat layer (get_or_create_thread, send_message) gates on
scenario status either, and inventing a stricter requirement here without a
PRD rule to back it would be an arbitrary asymmetry.

app.services.scenario_service.regenerate_scenario's own security-review note
about holding a DB session open across a Claude call applies identically
here - not re-solved as a drive-by, same Phase-4-adapter constraint.

Security review (2026-09-05), LOW, documented not fixed: `_conversation_
history_text` includes every message in a thread with no cap on message
count (each individual body is already bounded by MAX_MESSAGE_BODY_LENGTH,
just not how many of them accumulate) - a token-growth/cost concern on a
Builder-only route, not a security defect, and no PRD rule sets a
round-count limit to enforce here.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.chat import ChatMessage, ChatThread
from app.db.enums import ScenarioStatus, UserRole
from app.db.scenario import Scenario
from app.domain.claude_client import ClaudeClient
from app.domain.persona_chat import (
    Attitude,
    SufficiencyVerdict,
    build_known_information,
    run_sufficiency_check,
    suggest_pushback_message,
)
from app.services.chat import get_thread, list_messages
from app.services.scenario_service import ScenarioNotFoundError


class NoAnalystMessageYetError(ValueError):
    """Raised when a thread has no Analyst message yet for the pushback
    suggestion or sufficiency check to react to/grade."""


class ScenarioCancelledError(ValueError):
    """Raised when the thread's scenario has been cancelled - see module
    docstring for why this is the one status guard added here."""


# PRD 9.2 catalog row 17: the pushback loop must conclude gracefully
# (proceed to evaluation) rather than hang indefinitely. Flagged but
# deliberately not fixed during this module's own U23 security review
# ("no PRD rule sets a round-count limit to enforce here" - see this
# module's docstring) - row 17 is that PRD rule, closed here by U30. No
# PRD line names an exact number, so this is a plain module constant
# (same precedent as app.services.chat.MAX_MESSAGE_BODY_LENGTH), not an
# Analyst-adjustable threshold like live.exception_rule_threshold's rows.
MAX_PUSHBACK_ROUNDS = 5


class MaxPushbackRoundsExceededError(ValueError):
    """Raised by suggest_thread_pushback once the Analyst has already
    replied MAX_PUSHBACK_ROUNDS times in this thread - the AI stops
    suggesting further pushback so the loop concludes and the Builder
    proceeds to completing/evaluating the thread instead of an unbounded
    back-and-forth."""


def _latest_analyst_message(session: Session, thread_id: uuid.UUID) -> ChatMessage | None:
    return session.scalar(
        select(ChatMessage)
        .where(ChatMessage.thread_id == thread_id, ChatMessage.sender_role == UserRole.ANALYST)
        .order_by(ChatMessage.sent_at.desc())
        .limit(1)
    )


def _conversation_history_text(
    session: Session, thread_id: uuid.UUID, *, exclude_message_id: uuid.UUID | None = None
) -> str:
    """Code review finding: STAKEHOLDER_ROLEPLAY_TEMPLATE has two distinct
    sections - "Conversation so far" (history) and "The Analyst just said"
    (the current turn being reacted to) - so the message passed as the
    latter must be excluded here, or its body renders twice in the prompt.
    `check_thread_sufficiency` doesn't call this at all (its template has no
    conversation_history slot), so `exclude_message_id` only matters to
    `suggest_thread_pushback` below."""
    messages = [
        message for message in list_messages(session, thread_id) if message.id != exclude_message_id
    ]
    return "\n".join(f"{message.sender_role.value}: {message.body}" for message in messages)


def _load_thread_and_active_scenario(session: Session, thread_id: uuid.UUID) -> tuple[ChatThread, Scenario]:
    thread = get_thread(session, thread_id)
    scenario = session.get(Scenario, thread.scenario_id)
    if scenario is None:
        # Unreachable via any route today - ChatThread.scenario_id is a hard
        # FK (app.db.chat's own docstring) and Scenario rows are never
        # deleted, only status-transitioned (app.db.scenario's own
        # docstring) - kept as defense in depth rather than an unhandled
        # AttributeError on `scenario.status` below.
        raise ScenarioNotFoundError(f"scenario {thread.scenario_id} not found")
    if scenario.status == ScenarioStatus.CANCELLED:
        raise ScenarioCancelledError(f"scenario {scenario.id} is cancelled")
    return thread, scenario


def _analyst_message_count(session: Session, thread_id: uuid.UUID) -> int:
    return session.scalar(
        select(func.count())
        .select_from(ChatMessage)
        .where(ChatMessage.thread_id == thread_id, ChatMessage.sender_role == UserRole.ANALYST)
    )


def suggest_thread_pushback(
    session: Session, *, thread_id: uuid.UUID, attitude: Attitude, claude_client: ClaudeClient
) -> str:
    thread, scenario = _load_thread_and_active_scenario(session, thread_id)
    latest_analyst_message = _latest_analyst_message(session, thread_id)
    if latest_analyst_message is None:
        raise NoAnalystMessageYetError(
            f"chat thread {thread_id} has no Analyst message yet to react to"
        )
    if _analyst_message_count(session, thread_id) >= MAX_PUSHBACK_ROUNDS:
        raise MaxPushbackRoundsExceededError(
            f"chat thread {thread_id} has already reached the maximum of "
            f"{MAX_PUSHBACK_ROUNDS} pushback rounds"
        )
    return suggest_pushback_message(
        claude_client,
        persona=thread.persona,
        attitude=attitude,
        known_information=build_known_information(scenario.ground_truth),
        conversation_history=_conversation_history_text(
            session, thread_id, exclude_message_id=latest_analyst_message.id
        ),
        analyst_message=latest_analyst_message.body,
    )


def check_thread_sufficiency(
    session: Session, *, thread_id: uuid.UUID, claude_client: ClaudeClient
) -> SufficiencyVerdict:
    _thread, scenario = _load_thread_and_active_scenario(session, thread_id)
    latest_analyst_message = _latest_analyst_message(session, thread_id)
    if latest_analyst_message is None:
        raise NoAnalystMessageYetError(
            f"chat thread {thread_id} has no Analyst message yet to check"
        )
    return run_sufficiency_check(
        claude_client,
        ground_truth=scenario.ground_truth,
        analyst_message=latest_analyst_message.body,
    )
