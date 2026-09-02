"""Unit 4 (MEADOWOPS-DOM-002): simulation clock status transitions and
date-advance arithmetic (PRD 4.2). Pure Python, no DB.

Edge case catalog (PRD 9.2) row covered here (partially — see progress doc):
- #5 Simulation clock crossing a month/year boundary mid-scenario: this
  test proves the date arithmetic itself is correct; KPI-period correctness
  across that boundary is a later unit's (the KPI engine's) concern.
"""

from datetime import date

import pytest

from app.domain.simulation_clock import (
    ClockStatus,
    InvalidClockTransitionError,
    advance_date,
    validate_clock_transition,
)


@pytest.mark.parametrize(
    "from_status,to_status",
    [(ClockStatus.RUNNING, ClockStatus.PAUSED), (ClockStatus.PAUSED, ClockStatus.RUNNING)],
)
def test_valid_clock_transition_is_accepted(
    from_status: ClockStatus, to_status: ClockStatus
) -> None:
    validate_clock_transition(from_status, to_status)


@pytest.mark.parametrize(
    "from_status,to_status",
    [(ClockStatus.RUNNING, ClockStatus.RUNNING), (ClockStatus.PAUSED, ClockStatus.PAUSED)],
)
def test_transitioning_to_the_same_status_is_rejected(
    from_status: ClockStatus, to_status: ClockStatus
) -> None:
    with pytest.raises(InvalidClockTransitionError):
        validate_clock_transition(from_status, to_status)


def test_advance_date_crosses_a_month_boundary() -> None:
    assert advance_date(date(2026, 1, 28), days=5) == date(2026, 2, 2)


def test_advance_date_crosses_a_year_boundary() -> None:
    assert advance_date(date(2026, 12, 29), days=5) == date(2027, 1, 3)


def test_advance_date_crosses_a_leap_year_february() -> None:
    assert advance_date(date(2028, 2, 27), days=3) == date(2028, 3, 1)


def test_advance_date_rejects_zero_or_negative_days() -> None:
    with pytest.raises(ValueError):
        advance_date(date(2026, 1, 1), days=0)
    with pytest.raises(ValueError):
        advance_date(date(2026, 1, 1), days=-1)
