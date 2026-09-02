"""Unit 3 (MEADOWOPS-DOM-001): Decision & Event Ledger lifecycle state
machine (PRD 4.4). Every case below is mechanically enumerated by
harness-os's generate_tests from the spec's stateMachines — valid
transitions must succeed, every other pair must be rejected.
"""

import pytest

from app.domain.ledger import DecisionEventStatus, InvalidTransitionError, validate_transition

VALID_TRANSITIONS = [
    ("proposed", "clarification_requested"),
    ("proposed", "accepted"),
    ("proposed", "rejected"),
    ("proposed", "stale"),
    ("clarification_requested", "proposed"),
    ("clarification_requested", "accepted"),
    ("clarification_requested", "rejected"),
    ("clarification_requested", "stale"),
    ("stale", "accepted"),
    ("stale", "rejected"),
    ("accepted", "implemented"),
    ("accepted", "partially_implemented"),
    ("implemented", "outcome_observed"),
    ("partially_implemented", "outcome_observed"),
]

ALL_STATES = [s.value for s in DecisionEventStatus]
ALL_PAIRS = [(a, b) for a in ALL_STATES for b in ALL_STATES if a != b]
INVALID_TRANSITIONS = [pair for pair in ALL_PAIRS if pair not in VALID_TRANSITIONS]


@pytest.mark.parametrize("from_state,to_state", VALID_TRANSITIONS)
def test_valid_transition_is_accepted(from_state: str, to_state: str) -> None:
    validate_transition(DecisionEventStatus(from_state), DecisionEventStatus(to_state))


@pytest.mark.parametrize("from_state,to_state", INVALID_TRANSITIONS)
def test_invalid_transition_is_rejected(from_state: str, to_state: str) -> None:
    with pytest.raises(InvalidTransitionError):
        validate_transition(DecisionEventStatus(from_state), DecisionEventStatus(to_state))


def test_all_eight_states_are_covered_by_the_matrix() -> None:
    """Guards against silently losing a state if the enum ever changes
    without updating VALID_TRANSITIONS above."""
    assert set(ALL_STATES) == {
        "proposed",
        "clarification_requested",
        "accepted",
        "rejected",
        "implemented",
        "partially_implemented",
        "outcome_observed",
        "stale",
    }


def test_transitioning_to_the_same_state_is_rejected() -> None:
    with pytest.raises(InvalidTransitionError):
        validate_transition(DecisionEventStatus.PROPOSED, DecisionEventStatus.PROPOSED)
