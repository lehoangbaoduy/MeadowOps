"""Unit 24 (MEADOWOPS-DOM-018, business id MEADOWOPS-DOMAIN-013, PRD 4.4):
Decision & Event Ledger — the transactional layer over the DecisionEvent
ORM model and app.domain.ledger's pure state machine (both built at Unit 3;
nothing here migrates the schema). Same non-autocommit discipline as
app.services.scenario_service: callers own the transaction.

Every transition helper below follows the same shape as
app.services.scenario_service's approve_scenario/activate_scenario/
cancel_scenario: look up the row, run the domain state machine, stamp the
timestamp(s) PRD 4.4 attaches to that transition, flush, return the row.
InvalidTransitionError (app.domain.ledger) is caught and re-raised as this
module's own DecisionTransitionError, the same "domain error becomes a
service-level, API-friendly error" convention ScenarioTransitionError
already uses — callers here should not need to import app.domain.ledger at
all.

propose_decision never mutates an existing row to represent a new
recommendation, even when it supersedes one — PRD 9.2: "two
conflicting-outcome decisions on the same entity" must both be preserved,
never a silent overwrite. supersedes_id on the new row is how that link is
recorded; the old row is left exactly as it was.

find_callback_candidates only returns decisions that have actually been
decided-and-acted-on (implemented, partially implemented, or with an
observed outcome) — PRD 4.4's own callback example ("Last month you
recommended moving 40% of SKU-100 volume to Supplier S-002. Did it actually
improve service?") is always about a decision with a real-world
consequence to ask about, never one still sitting in proposed/
clarification_requested/rejected.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.ledger import ApprovalAuthority, DecisionEvent, DecisionOutcome, EntityType, RecordType
from app.domain.ledger import (
    DecisionEventStatus,
    InvalidTransitionError,
    is_decision_stale,
    validate_transition,
)


class DecisionEventNotFoundError(ValueError):
    pass


class DecisionTransitionError(ValueError):
    """Raised when the requested status change isn't a valid transition from
    the decision's current status (app.domain.ledger.validate_transition)."""


_CALLBACK_ELIGIBLE_STATUSES = (
    DecisionEventStatus.IMPLEMENTED,
    DecisionEventStatus.PARTIALLY_IMPLEMENTED,
    DecisionEventStatus.OUTCOME_OBSERVED,
)


def _get_decision(
    session: Session, decision_id: uuid.UUID, *, for_update: bool = False
) -> DecisionEvent:
    decision = session.get(DecisionEvent, decision_id, with_for_update=for_update or None)
    if decision is None:
        raise DecisionEventNotFoundError(f"decision event {decision_id} not found")
    return decision


def _get_decision_for_transition(session: Session, decision_id: uuid.UUID) -> DecisionEvent:
    """Security review of this unit, MEDIUM: every transition below used to
    fetch via a plain session.get() with no row lock — on Postgres READ
    COMMITTED (the default), two concurrent writers (e.g. an admin's
    accept_decision racing the scheduler's own flag_stale, which runs on
    its own independent Session, app.domain.scheduler._run_tick) could both
    read the pre-transition status, both pass validate_transition, and both
    write — last commit wins silently, no 409, producing a
    self-contradictory audit row (e.g. status=accepted with
    stale_flagged_at also populated). SELECT ... FOR UPDATE here closes
    that: the second writer blocks until the first transaction commits or
    rolls back, then re-reads the now-current status and (correctly) fails
    validate_transition instead of silently corrupting it."""
    return _get_decision(session, decision_id, for_update=True)


def _apply_transition(decision: DecisionEvent, to_status: DecisionEventStatus) -> None:
    try:
        validate_transition(decision.status, to_status)
    except InvalidTransitionError as exc:
        raise DecisionTransitionError(str(exc)) from exc
    decision.status = to_status


def propose_decision(
    session: Session,
    *,
    entity_type: EntityType,
    entity_id: str,
    title: str,
    summary: str,
    record_type: RecordType = RecordType.DECISION,
    scenario_id: uuid.UUID | None = None,
    approval_authority: ApprovalAuthority | None = None,
    supersedes_id: uuid.UUID | None = None,
) -> DecisionEvent:
    decision = DecisionEvent(
        record_type=record_type,
        status=DecisionEventStatus.PROPOSED,
        scenario_id=scenario_id,
        entity_type=entity_type,
        entity_id=entity_id,
        title=title,
        summary=summary,
        proposed_at=datetime.now(timezone.utc),
        approval_authority=approval_authority,
        supersedes_id=supersedes_id,
    )
    session.add(decision)
    session.flush()
    return decision


def request_clarification(session: Session, decision_id: uuid.UUID) -> DecisionEvent:
    decision = _get_decision_for_transition(session, decision_id)
    _apply_transition(decision, DecisionEventStatus.CLARIFICATION_REQUESTED)
    session.flush()
    return decision


def resubmit_decision(session: Session, decision_id: uuid.UUID) -> DecisionEvent:
    """Code review, MEDIUM: app.domain.ledger's own state machine allows
    CLARIFICATION_REQUESTED -> PROPOSED ("clarification answered, back on
    the table for a decision") - the one edge of the 14 this unit had left
    unwired. Deliberately does not also touch proposed_at - is_decision_
    stale measures age from the original proposal, not the last status
    change, so a decision that bounced through clarification once doesn't
    get a fresh staleness clock for having done so."""
    decision = _get_decision_for_transition(session, decision_id)
    _apply_transition(decision, DecisionEventStatus.PROPOSED)
    session.flush()
    return decision


def accept_decision(
    session: Session,
    decision_id: uuid.UUID,
    *,
    decided_by: str,
    approval_authority: ApprovalAuthority | None = None,
) -> DecisionEvent:
    decision = _get_decision_for_transition(session, decision_id)
    _apply_transition(decision, DecisionEventStatus.ACCEPTED)
    decision.decided_at = datetime.now(timezone.utc)
    decision.decided_by = decided_by
    if approval_authority is not None:
        decision.approval_authority = approval_authority
    session.flush()
    return decision


def reject_decision(session: Session, decision_id: uuid.UUID, *, decided_by: str) -> DecisionEvent:
    decision = _get_decision_for_transition(session, decision_id)
    _apply_transition(decision, DecisionEventStatus.REJECTED)
    decision.decided_at = datetime.now(timezone.utc)
    decision.decided_by = decided_by
    session.flush()
    return decision


def mark_implemented(session: Session, decision_id: uuid.UUID) -> DecisionEvent:
    decision = _get_decision_for_transition(session, decision_id)
    _apply_transition(decision, DecisionEventStatus.IMPLEMENTED)
    decision.implemented_at = datetime.now(timezone.utc)
    session.flush()
    return decision


def mark_partially_implemented(session: Session, decision_id: uuid.UUID) -> DecisionEvent:
    decision = _get_decision_for_transition(session, decision_id)
    _apply_transition(decision, DecisionEventStatus.PARTIALLY_IMPLEMENTED)
    decision.implemented_at = datetime.now(timezone.utc)
    session.flush()
    return decision


def record_outcome(
    session: Session, decision_id: uuid.UUID, *, outcome: DecisionOutcome, notes: str | None
) -> DecisionEvent:
    decision = _get_decision_for_transition(session, decision_id)
    _apply_transition(decision, DecisionEventStatus.OUTCOME_OBSERVED)
    decision.outcome = outcome
    decision.outcome_notes = notes
    decision.outcome_recorded_at = datetime.now(timezone.utc)
    session.flush()
    return decision


def flag_stale(session: Session, *, as_of: datetime, after_days: int) -> list[DecisionEvent]:
    """Meant to be called once per scheduler tick (app.domain.scheduler),
    same "pure predicate in app.domain, DB query here" split as every other
    service module in this project. Only PROPOSED/CLARIFICATION_REQUESTED
    *decision* rows are eligible — app.domain.ledger.validate_transition
    already encodes that STALE is only reachable from those two states, so
    a decision already ACCEPTED/REJECTED/etc. is filtered out here rather
    than relying on _apply_transition to reject it row-by-row; record_type
    is filtered the same way (code review, HIGH: app.db.ledger's own
    docstring says "only decisions carry the full lifecycle in status" —
    an operational_event row must never be flagged stale).

    `with_for_update(skip_locked=True)` (security review, MEDIUM): this
    runs on the scheduler's own independent Session
    (app.domain.scheduler._run_tick), concurrently with request-scoped
    sessions handling accept/reject/etc. on the same rows. Locking here
    means a row an admin request is mid-transition on is simply skipped
    this tick (picked up the next one) rather than the two writers racing
    to silently overwrite each other's outcome."""
    candidates = session.scalars(
        select(DecisionEvent)
        .where(
            DecisionEvent.record_type == RecordType.DECISION,
            DecisionEvent.status.in_(
                (DecisionEventStatus.PROPOSED, DecisionEventStatus.CLARIFICATION_REQUESTED)
            ),
        )
        .with_for_update(skip_locked=True)
    ).all()
    flagged: list[DecisionEvent] = []
    for decision in candidates:
        if is_decision_stale(proposed_at=decision.proposed_at, as_of=as_of, after_days=after_days):
            _apply_transition(decision, DecisionEventStatus.STALE)
            decision.stale_flagged_at = as_of
            flagged.append(decision)
    session.flush()
    return flagged


def find_callback_candidates(
    session: Session, *, entity_type: EntityType, entity_id: str, limit: int = 5
) -> list[DecisionEvent]:
    query = (
        select(DecisionEvent)
        .where(
            DecisionEvent.record_type == RecordType.DECISION,
            DecisionEvent.entity_type == entity_type,
            DecisionEvent.entity_id == entity_id,
            DecisionEvent.status.in_(_CALLBACK_ELIGIBLE_STATUSES),
        )
        .order_by(DecisionEvent.decided_at.desc())
        .limit(limit)
    )
    return list(session.scalars(query))


def get_decision(session: Session, decision_id: uuid.UUID) -> DecisionEvent:
    return _get_decision(session, decision_id)


def list_decisions(
    session: Session,
    *,
    status: DecisionEventStatus | None = None,
    entity_type: EntityType | None = None,
    entity_id: str | None = None,
) -> list[DecisionEvent]:
    query = select(DecisionEvent).order_by(DecisionEvent.created_at.desc())
    if status is not None:
        query = query.where(DecisionEvent.status == status)
    if entity_type is not None:
        query = query.where(DecisionEvent.entity_type == entity_type)
    if entity_id is not None:
        query = query.where(DecisionEvent.entity_id == entity_id)
    return list(session.scalars(query))
