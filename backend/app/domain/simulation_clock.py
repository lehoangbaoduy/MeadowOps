"""Simulation clock (PRD 4.2, spec MEADOWOPS-DOM-002): a simulated business
date, independent of the real calendar. Pure logic — the DB-backed singleton
row lives in app/db/world_state.py.
"""

import enum
from datetime import date, timedelta


class ClockStatus(str, enum.Enum):
    RUNNING = "running"
    PAUSED = "paused"


class InvalidClockTransitionError(ValueError):
    def __init__(self, from_status: ClockStatus, to_status: ClockStatus) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"cannot transition simulation clock from {from_status.value!r} to {to_status.value!r}")


def validate_clock_transition(from_status: ClockStatus, to_status: ClockStatus) -> None:
    if from_status == to_status:
        raise InvalidClockTransitionError(from_status, to_status)


def advance_date(current: date, days: int) -> date:
    """Advances the simulated business date by a positive number of days.
    Plain date arithmetic (Python's `date` already handles month/year/leap
    boundaries correctly) — kept as a named function so callers have one
    place to add business-day-only rules later if the team decides the
    simulation should skip weekends, without touching call sites."""
    if days <= 0:
        raise ValueError(f"days must be positive, got {days}")
    return current + timedelta(days=days)
