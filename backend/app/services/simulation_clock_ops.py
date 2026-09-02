"""Simulation clock service operations (PRD 4.2, spec MEADOWOPS-DOM-005):
DB-backed clock/world-state mutations. Pure status/date logic lives in
app.domain.simulation_clock; this module is the transactional layer that
locks the simulation_clock singleton row and writes world_state rows.

Picks up two gaps deferred out of earlier units' scope, both flagged as
deferred (not silently skipped) at the time:
- Unit 4: the concurrency-locked advance_simulation() operation.
- Unit 5: seeding the initial world_state (clean_baseline) + simulation_clock
  row.

Design split:
- seed_initial_world_state_and_clock() is a one-shot bootstrap operation,
  like app.services.baseline_data.seed_master_data() - commits internally
  only on the single call that actually performs the first-ever seed (every
  later call is a true no-op, no commit at all - the early-return happens
  before session.commit()). See its own docstring for the narrow window
  this still leaves for a caller with other uncommitted work pending in the
  same session the first time the database gets seeded.
- Every other function here (advance/pause/resume/snapshot/reset) does NOT
  commit - transaction boundaries belong to the caller (a future API route,
  matching DD-11's request-scoped session ownership), so these compose
  inside a single request's transaction and so tests can exercise them
  without permanently mutating the shared dev database's real clock state.

Every mutating operation locks the simulation_clock singleton row first
(SELECT ... FOR UPDATE) - the one real contended resource (world_state rows
are independent, append-only inserts with no shared mutable state) - so
concurrent callers serialize instead of racing (PRD 9.2 row 6).

current_world_state_id (migration 0008, added this unit): Unit 4 left
world_state's "current head" undiscoverable except by row ordering, and
Postgres's now() is frozen per-transaction-start, not per-statement - two
world_state rows inserted within one open transaction (the exact composition
this module is designed for) get an identical created_at, so ORDER BY
created_at DESC LIMIT 1 cannot reliably answer "which is current." Tracked
explicitly on the singleton clock row instead, self-caught while designing
this module, before any review round.
"""

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.world_state import SimulationClock, WorldState, WorldStateKind
from app.domain.simulation_clock import ClockStatus, advance_date, validate_clock_transition

CLEAN_BASELINE_SIMULATION_DATE = date(2026, 1, 1)
CLEAN_BASELINE_SEED = "baseline-v1"
CLEAN_BASELINE_LABEL = "Clean Baseline"


class SimulationPausedError(RuntimeError):
    """Raised by advance_simulation when the clock is paused."""


class SimulationClockNotSeededError(RuntimeError):
    """Raised by snapshot_simulation/reset_simulation when the singleton
    clock row has no current_world_state_id set - normally impossible
    through seed_initial_world_state_and_clock's own path (it always sets
    both atomically), but reachable if the column is ever cleared by a
    manual repair or an alembic downgrade/upgrade round-trip on migration
    0008 while world_state rows already exist (which makes the seed
    function's own "any row exists" idempotency check silently no-op
    instead of re-establishing the pointer)."""


def seed_initial_world_state_and_clock(session: Session) -> None:
    """Idempotent: a no-op if any world_state row already exists — and a
    true no-op, with no commit at all, once that's the case (the early
    return happens before session.commit()). It's only on a genuinely
    unseeded database that this function commits for real, matching
    app.services.baseline_data.seed_master_data()'s one-shot-bootstrap
    design.

    That narrows, but doesn't remove, the mid-sequence-commit risk a
    security review of this unit raised: the risk is real only for the
    single call that actually performs the first-ever seed (there is no
    way for another op in this module to run before that call, since every
    other function here requires the singleton clock row seed() itself
    creates) — but session.commit() commits the *whole* session, so if a
    caller has unrelated uncommitted work pending in the same session
    the first time it calls this function, that work gets committed too.
    Safest usage: call this on its own session, separate from any other
    composed sequence, unless the caller has verified the database is
    already seeded.
    """
    existing = session.execute(select(WorldState.id).limit(1)).first()
    if existing is not None:
        return
    world_state = WorldState(
        kind=WorldStateKind.CLEAN_BASELINE,
        simulation_date=CLEAN_BASELINE_SIMULATION_DATE,
        seed=CLEAN_BASELINE_SEED,
        label=CLEAN_BASELINE_LABEL,
    )
    session.add(world_state)
    session.flush()
    session.add(
        SimulationClock(
            id=1,
            simulation_date=CLEAN_BASELINE_SIMULATION_DATE,
            status=ClockStatus.RUNNING,
            current_world_state_id=world_state.id,
        )
    )
    session.commit()


def _lock_clock(session: Session) -> SimulationClock:
    return session.execute(
        select(SimulationClock).where(SimulationClock.id == 1).with_for_update()
    ).scalar_one()


def advance_simulation(session: Session, *, days: int = 1) -> date:
    clock = _lock_clock(session)
    if clock.status != ClockStatus.RUNNING:
        raise SimulationPausedError("cannot advance the simulation clock while paused")
    clock.simulation_date = advance_date(clock.simulation_date, days)
    clock.last_advanced_at = func.now()
    session.flush()
    session.refresh(clock)
    return clock.simulation_date


def pause_simulation(session: Session) -> None:
    clock = _lock_clock(session)
    validate_clock_transition(clock.status, ClockStatus.PAUSED)
    clock.status = ClockStatus.PAUSED
    session.flush()


def resume_simulation(session: Session) -> None:
    clock = _lock_clock(session)
    validate_clock_transition(clock.status, ClockStatus.RUNNING)
    clock.status = ClockStatus.RUNNING
    session.flush()


def snapshot_simulation(session: Session, *, label: str) -> uuid.UUID:
    clock = _lock_clock(session)
    if clock.current_world_state_id is None:
        raise SimulationClockNotSeededError(
            "simulation_clock.current_world_state_id is unset - run "
            "seed_initial_world_state_and_clock or repair manually"
        )
    head = session.get(WorldState, clock.current_world_state_id)
    snapshot = WorldState(
        kind=WorldStateKind.SNAPSHOT,
        simulation_date=clock.simulation_date,
        seed=head.seed,
        label=label,
        parent_id=head.id,
    )
    session.add(snapshot)
    session.flush()
    clock.current_world_state_id = snapshot.id
    session.flush()
    return snapshot.id


def reset_simulation(session: Session, *, label: str = "Reset") -> uuid.UUID:
    clock = _lock_clock(session)
    if clock.current_world_state_id is None:
        raise SimulationClockNotSeededError(
            "simulation_clock.current_world_state_id is unset - run "
            "seed_initial_world_state_and_clock or repair manually"
        )
    head = session.get(WorldState, clock.current_world_state_id)
    root = session.execute(
        select(WorldState).where(
            WorldState.kind == WorldStateKind.CLEAN_BASELINE,
            WorldState.parent_id.is_(None),
        )
    ).scalar_one()
    reset_row = WorldState(
        kind=WorldStateKind.RESET,
        simulation_date=root.simulation_date,
        seed=root.seed,
        label=label,
        parent_id=head.id,
    )
    session.add(reset_row)
    session.flush()
    clock.current_world_state_id = reset_row.id
    clock.simulation_date = root.simulation_date
    clock.status = ClockStatus.RUNNING
    session.flush()
    return reset_row.id
