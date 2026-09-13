"""Unit 24 (MEADOWOPS-DOM-018, PRD 4.4): pure predicate for stale-decision
flagging. app.services.ledger.flag_stale owns finding candidate rows in the
database; this only tests the age comparison itself, in isolation.
"""

from datetime import datetime, timezone

from app.domain.ledger import is_decision_stale


def test_exactly_at_the_threshold_is_stale() -> None:
    proposed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    as_of = datetime(2026, 1, 15, tzinfo=timezone.utc)
    assert is_decision_stale(proposed_at=proposed_at, as_of=as_of, after_days=14) is True


def test_one_second_before_the_threshold_is_not_stale() -> None:
    proposed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    as_of = datetime(2026, 1, 14, 23, 59, 59, tzinfo=timezone.utc)
    assert is_decision_stale(proposed_at=proposed_at, as_of=as_of, after_days=14) is False


def test_well_past_the_threshold_is_stale() -> None:
    proposed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    as_of = datetime(2026, 3, 1, tzinfo=timezone.utc)
    assert is_decision_stale(proposed_at=proposed_at, as_of=as_of, after_days=14) is True


def test_zero_after_days_means_immediately_stale() -> None:
    proposed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert is_decision_stale(proposed_at=proposed_at, as_of=proposed_at, after_days=0) is True
