"""Decision & Event Ledger lifecycle (PRD 4.4, spec MEADOWOPS-DOM-001).

Transition validity is enforced here, in the application/service layer, not
via a database trigger or CHECK constraint: the state machine has 14 valid
edges out of 56 possible ordered pairs across 8 states, which is simple to
express and exhaustively test as a Python lookup table but would be an
unwieldy, hard-to-audit SQL CHECK expression. The Postgres enum type on the
`status` column (see app/db/ledger.py) still guarantees only these 8 values
are ever stored, structurally.
"""

import enum


class DecisionEventStatus(str, enum.Enum):
    PROPOSED = "proposed"
    CLARIFICATION_REQUESTED = "clarification_requested"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    IMPLEMENTED = "implemented"
    PARTIALLY_IMPLEMENTED = "partially_implemented"
    OUTCOME_OBSERVED = "outcome_observed"
    STALE = "stale"


class InvalidTransitionError(ValueError):
    def __init__(self, from_state: DecisionEventStatus, to_state: DecisionEventStatus) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"cannot transition Decision & Event record from {from_state.value!r} to {to_state.value!r}")


_ALLOWED_TRANSITIONS: dict[DecisionEventStatus, frozenset[DecisionEventStatus]] = {
    DecisionEventStatus.PROPOSED: frozenset(
        {
            DecisionEventStatus.CLARIFICATION_REQUESTED,
            DecisionEventStatus.ACCEPTED,
            DecisionEventStatus.REJECTED,
            DecisionEventStatus.STALE,
        }
    ),
    DecisionEventStatus.CLARIFICATION_REQUESTED: frozenset(
        {
            DecisionEventStatus.PROPOSED,
            DecisionEventStatus.ACCEPTED,
            DecisionEventStatus.REJECTED,
            DecisionEventStatus.STALE,
        }
    ),
    DecisionEventStatus.STALE: frozenset(
        {DecisionEventStatus.ACCEPTED, DecisionEventStatus.REJECTED}
    ),
    DecisionEventStatus.ACCEPTED: frozenset(
        {DecisionEventStatus.IMPLEMENTED, DecisionEventStatus.PARTIALLY_IMPLEMENTED}
    ),
    DecisionEventStatus.REJECTED: frozenset(),
    DecisionEventStatus.IMPLEMENTED: frozenset({DecisionEventStatus.OUTCOME_OBSERVED}),
    DecisionEventStatus.PARTIALLY_IMPLEMENTED: frozenset({DecisionEventStatus.OUTCOME_OBSERVED}),
    DecisionEventStatus.OUTCOME_OBSERVED: frozenset(),
}


def validate_transition(
    from_state: DecisionEventStatus, to_state: DecisionEventStatus
) -> None:
    """Raises InvalidTransitionError unless (from_state -> to_state) is one
    of the 14 edges the ledger's lifecycle (PRD 4.4) allows. Callers apply
    this before persisting a status change; it does not touch the database
    itself."""
    if to_state not in _ALLOWED_TRANSITIONS[from_state]:
        raise InvalidTransitionError(from_state, to_state)
