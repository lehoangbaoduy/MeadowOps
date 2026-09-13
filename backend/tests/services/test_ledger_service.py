"""Unit 24 (MEADOWOPS-DOM-018, business id MEADOWOPS-DOMAIN-013, PRD 4.4):
Decision & Event Ledger service layer - the transactional glue between
app.domain.ledger's pure state machine and the real `live.decision_event`
table (already built at Unit 3; nothing here migrates the schema). Same
non-autocommit discipline as tests/services/test_scenario_service.py: runs
against the real seeded baseline data inside an uncommitted transaction per
test, rolled back via Session.close()'s implicit rollback.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.db.auth import User
from app.db.dimensions import Supplier
from app.db.enums import UserRole
from app.db.ledger import ApprovalAuthority, DecisionOutcome, EntityType, RecordType
from app.domain.ledger import DecisionEventStatus
from app.services.baseline_data import seed_master_data
from app.services.ledger import (
    DecisionEventNotFoundError,
    DecisionTransitionError,
    accept_decision,
    find_callback_candidates,
    flag_stale,
    get_decision,
    list_decisions,
    mark_implemented,
    mark_partially_implemented,
    propose_decision,
    record_outcome,
    reject_decision,
    request_clarification,
    resubmit_decision,
)

_BUILDER_EMAIL = "zztest-ledger-builder@meadowops.local"


@pytest.fixture
def session():
    engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
    with Session(engine) as session:
        session.execute(delete(User).where(User.email == _BUILDER_EMAIL))
        session.commit()
        seed_master_data(session)
        session.commit()
        yield session
        session.rollback()
        session.execute(delete(User).where(User.email == _BUILDER_EMAIL))
        session.commit()
    engine.dispose()


@pytest.fixture
def builder_id(session: Session) -> uuid.UUID:
    user = User(
        email=_BUILDER_EMAIL,
        password_hash="not-a-real-hash",
        role=UserRole.ADMIN,
        is_active=True,
    )
    session.add(user)
    session.flush()
    return user.id


def _propose(session: Session, **overrides) -> "DecisionEvent":  # noqa: F821
    kwargs = dict(
        entity_type=EntityType.SUPPLIER,
        entity_id="SUP-001",
        title="Move 40% of SKU-100 volume to Supplier S-002",
        summary="Supplier S-001 has repeated late shipments; recommend partial reallocation.",
    )
    kwargs.update(overrides)
    return propose_decision(session, **kwargs)


class TestProposeDecision:
    def test_creates_a_proposed_decision_with_a_proposed_at_timestamp(self, session: Session) -> None:
        decision = _propose(session)
        assert decision.status == DecisionEventStatus.PROPOSED
        assert decision.record_type == RecordType.DECISION
        assert decision.proposed_at is not None
        assert decision.id is not None

    def test_defaults_to_no_supersedes_id(self, session: Session) -> None:
        decision = _propose(session)
        assert decision.supersedes_id is None

    def test_a_new_decision_can_declare_it_supersedes_an_earlier_one(self, session: Session) -> None:
        # PRD 9.2: two conflicting-outcome decisions on the same entity are
        # both preserved, never a silent overwrite - propose_decision always
        # inserts a new row, and supersedes_id is how a later one points
        # back at the one it replaces.
        first = _propose(session)
        second = _propose(session, supersedes_id=first.id, title="Reverse course - keep volume with S-001")
        assert second.supersedes_id == first.id
        assert session.get(type(first), first.id) is not None

    def test_an_unknown_supersedes_id_raises_integrity_error(self, session: Session) -> None:
        # Code review, HIGH: supersedes_id is a real hard FK
        # (app.db.ledger.DecisionEvent.supersedes_id) - the API layer maps
        # this to a 409 (tests/api/test_ledger_api.py); at the service
        # layer it's a plain IntegrityError, same as any other FK
        # violation in this codebase (e.g. Scenario.created_by).
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            _propose(session, supersedes_id=uuid.uuid4())


class TestRequestClarification:
    def test_moves_a_proposed_decision_to_clarification_requested(self, session: Session) -> None:
        decision = _propose(session)
        updated = request_clarification(session, decision.id)
        assert updated.status == DecisionEventStatus.CLARIFICATION_REQUESTED

    def test_raises_decision_transition_error_from_an_invalid_state(self, session: Session) -> None:
        decision = _propose(session)
        accept_decision(session, decision.id, decided_by="builder-1")
        with pytest.raises(DecisionTransitionError):
            request_clarification(session, decision.id)


class TestResubmitDecision:
    def test_moves_clarification_requested_back_to_proposed(self, session: Session) -> None:
        decision = _propose(session)
        request_clarification(session, decision.id)
        updated = resubmit_decision(session, decision.id)
        assert updated.status == DecisionEventStatus.PROPOSED

    def test_does_not_change_proposed_at(self, session: Session) -> None:
        decision = _propose(session)
        original_proposed_at = decision.proposed_at
        request_clarification(session, decision.id)
        updated = resubmit_decision(session, decision.id)
        assert updated.proposed_at == original_proposed_at

    def test_raises_decision_transition_error_from_an_invalid_state(self, session: Session) -> None:
        decision = _propose(session)
        with pytest.raises(DecisionTransitionError):
            resubmit_decision(session, decision.id)

    def test_raises_not_found_for_an_unknown_id(self, session: Session) -> None:
        with pytest.raises(DecisionEventNotFoundError):
            resubmit_decision(session, uuid.uuid4())

    def test_raises_not_found_for_an_unknown_id(self, session: Session) -> None:
        with pytest.raises(DecisionEventNotFoundError):
            request_clarification(session, uuid.uuid4())


class TestAcceptDecision:
    def test_moves_to_accepted_and_stamps_decided_at_and_decided_by(self, session: Session) -> None:
        decision = _propose(session)
        updated = accept_decision(session, decision.id, decided_by="builder-1")
        assert updated.status == DecisionEventStatus.ACCEPTED
        assert updated.decided_by == "builder-1"
        assert updated.decided_at is not None

    def test_can_set_approval_authority_at_accept_time(self, session: Session) -> None:
        decision = _propose(session)
        updated = accept_decision(
            session, decision.id, decided_by="builder-1", approval_authority=ApprovalAuthority.MANAGER
        )
        assert updated.approval_authority == ApprovalAuthority.MANAGER

    def test_raises_decision_transition_error_from_rejected(self, session: Session) -> None:
        decision = _propose(session)
        reject_decision(session, decision.id, decided_by="builder-1")
        with pytest.raises(DecisionTransitionError):
            accept_decision(session, decision.id, decided_by="builder-1")


class TestRejectDecision:
    def test_moves_to_rejected_and_stamps_decided_at_and_decided_by(self, session: Session) -> None:
        decision = _propose(session)
        updated = reject_decision(session, decision.id, decided_by="builder-1")
        assert updated.status == DecisionEventStatus.REJECTED
        assert updated.decided_by == "builder-1"
        assert updated.decided_at is not None

    def test_rejected_is_terminal(self, session: Session) -> None:
        decision = _propose(session)
        reject_decision(session, decision.id, decided_by="builder-1")
        with pytest.raises(DecisionTransitionError):
            reject_decision(session, decision.id, decided_by="builder-1")


class TestMarkImplemented:
    def test_moves_accepted_to_implemented_and_stamps_implemented_at(self, session: Session) -> None:
        decision = _propose(session)
        accept_decision(session, decision.id, decided_by="builder-1")
        updated = mark_implemented(session, decision.id)
        assert updated.status == DecisionEventStatus.IMPLEMENTED
        assert updated.implemented_at is not None

    def test_raises_decision_transition_error_from_proposed(self, session: Session) -> None:
        decision = _propose(session)
        with pytest.raises(DecisionTransitionError):
            mark_implemented(session, decision.id)


class TestMarkPartiallyImplemented:
    def test_moves_accepted_to_partially_implemented(self, session: Session) -> None:
        decision = _propose(session)
        accept_decision(session, decision.id, decided_by="builder-1")
        updated = mark_partially_implemented(session, decision.id)
        assert updated.status == DecisionEventStatus.PARTIALLY_IMPLEMENTED
        assert updated.implemented_at is not None


class TestRecordOutcome:
    def test_moves_implemented_to_outcome_observed_and_stamps_notes(self, session: Session) -> None:
        decision = _propose(session)
        accept_decision(session, decision.id, decided_by="builder-1")
        mark_implemented(session, decision.id)
        updated = record_outcome(
            session, decision.id, outcome=DecisionOutcome.SUCCEEDED, notes="Service level improved 6pts."
        )
        assert updated.status == DecisionEventStatus.OUTCOME_OBSERVED
        assert updated.outcome == DecisionOutcome.SUCCEEDED
        assert updated.outcome_notes == "Service level improved 6pts."
        assert updated.outcome_recorded_at is not None

    def test_moves_partially_implemented_to_outcome_observed(self, session: Session) -> None:
        decision = _propose(session)
        accept_decision(session, decision.id, decided_by="builder-1")
        mark_partially_implemented(session, decision.id)
        updated = record_outcome(session, decision.id, outcome=DecisionOutcome.PARTIALLY_SUCCEEDED, notes=None)
        assert updated.status == DecisionEventStatus.OUTCOME_OBSERVED

    def test_raises_decision_transition_error_from_proposed(self, session: Session) -> None:
        decision = _propose(session)
        with pytest.raises(DecisionTransitionError):
            record_outcome(session, decision.id, outcome=DecisionOutcome.FAILED, notes=None)


class TestFlagStale:
    def test_flags_a_proposed_decision_older_than_the_threshold(self, session: Session) -> None:
        decision = _propose(session)
        decision.proposed_at = datetime.now(timezone.utc) - timedelta(days=30)
        session.flush()
        flagged = flag_stale(session, as_of=datetime.now(timezone.utc), after_days=14)
        assert decision.id in {d.id for d in flagged}
        session.refresh(decision)
        assert decision.status == DecisionEventStatus.STALE
        assert decision.stale_flagged_at is not None

    def test_does_not_flag_a_recent_proposed_decision(self, session: Session) -> None:
        decision = _propose(session)
        flagged = flag_stale(session, as_of=datetime.now(timezone.utc), after_days=14)
        assert decision.id not in {d.id for d in flagged}
        assert decision.status == DecisionEventStatus.PROPOSED

    def test_does_not_flag_an_already_accepted_decision(self, session: Session) -> None:
        decision = _propose(session)
        decision.proposed_at = datetime.now(timezone.utc) - timedelta(days=30)
        accept_decision(session, decision.id, decided_by="builder-1")
        flagged = flag_stale(session, as_of=datetime.now(timezone.utc), after_days=14)
        assert decision.id not in {d.id for d in flagged}

    def test_flags_an_old_clarification_requested_decision_too(self, session: Session) -> None:
        decision = _propose(session)
        request_clarification(session, decision.id)
        decision.proposed_at = datetime.now(timezone.utc) - timedelta(days=30)
        session.flush()
        flagged = flag_stale(session, as_of=datetime.now(timezone.utc), after_days=14)
        assert decision.id in {d.id for d in flagged}

    def test_does_not_flag_an_operational_event_record(self, session: Session) -> None:
        # Code review, HIGH: app.db.ledger's own docstring says "only
        # decisions carry the full lifecycle in status" - the API route no
        # longer accepts record_type="operational_event" (schemas/ledger.py),
        # but the service function itself still allows it (a future
        # operational-event creation path may use it directly), so
        # flag_stale must filter it out defensively rather than trust the
        # API layer alone.
        event = _propose(session, record_type=RecordType.OPERATIONAL_EVENT)
        event.proposed_at = datetime.now(timezone.utc) - timedelta(days=30)
        session.flush()
        flagged = flag_stale(session, as_of=datetime.now(timezone.utc), after_days=14)
        assert event.id not in {d.id for d in flagged}


class TestFindCallbackCandidates:
    def test_returns_empty_for_an_entity_with_no_decisions(self, session: Session) -> None:
        assert find_callback_candidates(session, entity_type=EntityType.SUPPLIER, entity_id="SUP-999") == []

    def test_excludes_a_still_proposed_decision(self, session: Session) -> None:
        _propose(session, entity_id="SUP-042")
        candidates = find_callback_candidates(session, entity_type=EntityType.SUPPLIER, entity_id="SUP-042")
        assert candidates == []

    def test_includes_an_implemented_decision(self, session: Session) -> None:
        decision = _propose(session, entity_id="SUP-042")
        accept_decision(session, decision.id, decided_by="builder-1")
        mark_implemented(session, decision.id)
        candidates = find_callback_candidates(session, entity_type=EntityType.SUPPLIER, entity_id="SUP-042")
        assert [c.id for c in candidates] == [decision.id]

    def test_includes_an_outcome_observed_decision(self, session: Session) -> None:
        decision = _propose(session, entity_id="SUP-042")
        accept_decision(session, decision.id, decided_by="builder-1")
        mark_implemented(session, decision.id)
        record_outcome(session, decision.id, outcome=DecisionOutcome.SUCCEEDED, notes=None)
        candidates = find_callback_candidates(session, entity_type=EntityType.SUPPLIER, entity_id="SUP-042")
        assert [c.id for c in candidates] == [decision.id]

    def test_excludes_an_implemented_operational_event_record(self, session: Session) -> None:
        event = _propose(session, entity_id="SUP-042", record_type=RecordType.OPERATIONAL_EVENT)
        accept_decision(session, event.id, decided_by="builder-1")
        mark_implemented(session, event.id)
        candidates = find_callback_candidates(session, entity_type=EntityType.SUPPLIER, entity_id="SUP-042")
        assert candidates == []

    def test_does_not_cross_entities(self, session: Session) -> None:
        decision = _propose(session, entity_id="SUP-042")
        accept_decision(session, decision.id, decided_by="builder-1")
        mark_implemented(session, decision.id)
        candidates = find_callback_candidates(session, entity_type=EntityType.SUPPLIER, entity_id="SUP-043")
        assert candidates == []

    def test_does_not_cross_entity_types(self, session: Session) -> None:
        decision = _propose(session, entity_type=EntityType.SUPPLIER, entity_id="X-1")
        accept_decision(session, decision.id, decided_by="builder-1")
        mark_implemented(session, decision.id)
        candidates = find_callback_candidates(session, entity_type=EntityType.WAREHOUSE, entity_id="X-1")
        assert candidates == []

    def test_still_surfaces_a_candidate_after_its_entity_is_deactivated(
        self, session: Session
    ) -> None:
        # PRD 9.2 catalog row 12: a callback candidate referencing a
        # decision whose entity was later deactivated must still be
        # findable. entity_id has no FK to live.supplier (see
        # app.db.ledger's own docstring) - this proves it against a real,
        # seeded supplier row, not just a free-standing string id.
        decision = _propose(session, entity_type=EntityType.SUPPLIER, entity_id="S-001")
        accept_decision(session, decision.id, decided_by="builder-1")
        mark_implemented(session, decision.id)

        supplier = session.get(Supplier, "S-001")
        supplier.is_active = False
        session.flush()

        candidates = find_callback_candidates(session, entity_type=EntityType.SUPPLIER, entity_id="S-001")
        assert [c.id for c in candidates] == [decision.id]


class TestGetAndListDecisions:
    def test_get_decision_raises_not_found_for_an_unknown_id(self, session: Session) -> None:
        with pytest.raises(DecisionEventNotFoundError):
            get_decision(session, uuid.uuid4())

    def test_get_decision_returns_the_row(self, session: Session) -> None:
        decision = _propose(session)
        assert get_decision(session, decision.id).id == decision.id

    def test_list_decisions_filters_by_status(self, session: Session) -> None:
        proposed = _propose(session, entity_id="LIST-1")
        accepted = _propose(session, entity_id="LIST-2")
        accept_decision(session, accepted.id, decided_by="builder-1")
        results = list_decisions(session, status=DecisionEventStatus.ACCEPTED)
        ids = {d.id for d in results}
        assert accepted.id in ids
        assert proposed.id not in ids

    def test_list_decisions_filters_by_entity(self, session: Session) -> None:
        _propose(session, entity_id="LIST-A")
        target = _propose(session, entity_id="LIST-B")
        results = list_decisions(session, entity_type=EntityType.SUPPLIER, entity_id="LIST-B")
        assert [d.id for d in results] == [target.id]
