"""Unit 12a (MEADOWOPS-DOM-005): simulation clock service operations -
picks up Unit 4's deferred locked advance_simulation() and Unit 5's
deferred initial world_state/simulation_clock seed row (PRD 4.2, Phase 1's
"skeleton" bar: advance/pause/snapshot/reset working).

Every mutating test below relies on Session.close()'s implicit rollback of
any transaction begun after seed_initial_world_state_and_clock()'s own
internal commit - the same non-autocommit discipline as every other DB test
in this suite (Units 2/3/4/5/10), so none of these tests ever leaves the
shared dev database's real clock in a mutated (advanced/paused/reset)
state. seed_initial_world_state_and_clock() itself is the one function here
that legitimately commits for real (see the service module's own
docstring) - every test calls it as its own arrange step, which is either
the real first-ever commit or an idempotent no-op.


Edge case catalog (PRD 9.2) rows this file covers, alongside Unit 4's own:
- #6 concurrent snapshot/reset serialized safely: the locking itself is
  proven separately, with real cross-connection blocking, in
  test_simulation_clock_ops_concurrency.py - not here.
- #7 reset never invalidates an in-flight scenario's own world_state_id:
  same service-layer proxy Unit 4 already established (no Scenario table
  until Phase 3), extended here to the reset *operation* rather than just
  the schema-level "rows are append-only" guarantee.
"""

import os
import uuid

import psycopg
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.world_state import SimulationClock, WorldState, WorldStateKind
from app.domain.simulation_clock import (
    ClockStatus,
    InvalidClockTransitionError,
    advance_date,
)
from app.services.simulation_clock_ops import (
    CLEAN_BASELINE_SEED,
    CLEAN_BASELINE_SIMULATION_DATE,
    SimulationClockNotSeededError,
    SimulationPausedError,
    advance_simulation,
    pause_simulation,
    reset_simulation,
    resume_simulation,
    seed_initial_world_state_and_clock,
    snapshot_simulation,
)


@pytest.fixture
def session():
    engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
    with Session(engine) as session:
        yield session
    engine.dispose()


def _root(session: Session) -> WorldState:
    return session.execute(
        select(WorldState).where(WorldState.kind == WorldStateKind.CLEAN_BASELINE)
    ).scalar_one()


class TestSeedInitialWorldStateAndClock:
    def test_creates_exactly_one_clean_baseline_world_state_row(self, session: Session) -> None:
        seed_initial_world_state_and_clock(session)
        seed_initial_world_state_and_clock(session)  # idempotency: second call is a no-op
        rows = (
            session.execute(
                select(WorldState).where(WorldState.kind == WorldStateKind.CLEAN_BASELINE)
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].simulation_date == CLEAN_BASELINE_SIMULATION_DATE
        assert rows[0].parent_id is None

    def test_creates_the_singleton_clock_row_pointing_at_the_baseline(self, session: Session) -> None:
        seed_initial_world_state_and_clock(session)
        clock = session.get(SimulationClock, 1)
        root = _root(session)
        assert clock is not None
        assert clock.simulation_date == CLEAN_BASELINE_SIMULATION_DATE
        assert clock.status == ClockStatus.RUNNING
        assert clock.current_world_state_id == root.id


class TestAdvanceSimulation:
    def test_advances_the_date_by_the_requested_number_of_days(self, session: Session) -> None:
        seed_initial_world_state_and_clock(session)
        before = session.get(SimulationClock, 1).simulation_date
        result = advance_simulation(session, days=5)
        assert result == advance_date(before, 5)
        assert session.get(SimulationClock, 1).simulation_date == advance_date(before, 5)

    def test_records_last_advanced_at(self, session: Session) -> None:
        seed_initial_world_state_and_clock(session)
        assert session.get(SimulationClock, 1).last_advanced_at is None
        advance_simulation(session, days=1)
        assert session.get(SimulationClock, 1).last_advanced_at is not None

    def test_raises_when_the_clock_is_paused(self, session: Session) -> None:
        seed_initial_world_state_and_clock(session)
        pause_simulation(session)
        with pytest.raises(SimulationPausedError):
            advance_simulation(session, days=1)

    def test_rejects_zero_or_negative_days(self, session: Session) -> None:
        seed_initial_world_state_and_clock(session)
        with pytest.raises(ValueError):
            advance_simulation(session, days=0)


class TestPauseAndResume:
    def test_pause_transitions_running_to_paused(self, session: Session) -> None:
        seed_initial_world_state_and_clock(session)
        pause_simulation(session)
        assert session.get(SimulationClock, 1).status == ClockStatus.PAUSED

    def test_pausing_an_already_paused_clock_raises(self, session: Session) -> None:
        seed_initial_world_state_and_clock(session)
        pause_simulation(session)
        with pytest.raises(InvalidClockTransitionError):
            pause_simulation(session)

    def test_resume_transitions_paused_to_running(self, session: Session) -> None:
        seed_initial_world_state_and_clock(session)
        pause_simulation(session)
        resume_simulation(session)
        assert session.get(SimulationClock, 1).status == ClockStatus.RUNNING

    def test_resuming_an_already_running_clock_raises(self, session: Session) -> None:
        seed_initial_world_state_and_clock(session)
        with pytest.raises(InvalidClockTransitionError):
            resume_simulation(session)


class TestSnapshotSimulation:
    def test_creates_a_new_world_state_row_pinned_to_the_current_head(self, session: Session) -> None:
        seed_initial_world_state_and_clock(session)
        root = _root(session)
        snapshot_id = snapshot_simulation(session, label="pre-scenario snapshot")
        snapshot = session.get(WorldState, snapshot_id)
        assert snapshot.kind == WorldStateKind.SNAPSHOT
        assert snapshot.parent_id == root.id
        assert snapshot.label == "pre-scenario snapshot"

    def test_snapshot_uses_the_clocks_current_date_not_the_roots(self, session: Session) -> None:
        seed_initial_world_state_and_clock(session)
        advance_simulation(session, days=10)
        advanced_date = session.get(SimulationClock, 1).simulation_date
        snapshot_id = snapshot_simulation(session, label="after advance")
        assert session.get(WorldState, snapshot_id).simulation_date == advanced_date

    def test_advances_the_clocks_current_world_state_pointer(self, session: Session) -> None:
        seed_initial_world_state_and_clock(session)
        snapshot_id = snapshot_simulation(session, label="a")
        assert session.get(SimulationClock, 1).current_world_state_id == snapshot_id
        # a second snapshot chains from the first, not from the root - proves
        # the pointer (not created_at ordering) is what "current head" means
        second_id = snapshot_simulation(session, label="b")
        assert session.get(WorldState, second_id).parent_id == snapshot_id
        assert session.get(SimulationClock, 1).current_world_state_id == second_id


class TestResetSimulation:
    def test_creates_a_new_world_state_row_never_mutating_an_earlier_one(self, session: Session) -> None:
        seed_initial_world_state_and_clock(session)
        root = _root(session)
        original_root_date = root.simulation_date
        advance_simulation(session, days=20)
        reset_id = reset_simulation(session)
        session.refresh(root)
        assert root.simulation_date == original_root_date
        reset_row = session.get(WorldState, reset_id)
        assert reset_row.kind == WorldStateKind.RESET
        assert reset_row.parent_id == root.id

    def test_resets_the_clock_back_to_the_clean_baseline_date_and_running_status(
        self, session: Session
    ) -> None:
        seed_initial_world_state_and_clock(session)
        advance_simulation(session, days=20)
        pause_simulation(session)
        reset_simulation(session)
        clock = session.get(SimulationClock, 1)
        assert clock.simulation_date == CLEAN_BASELINE_SIMULATION_DATE
        assert clock.status == ClockStatus.RUNNING

    def test_an_earlier_world_state_id_still_resolves_after_repeated_resets(
        self, session: Session
    ) -> None:
        # PRD 9.2 row 7 proxy, same framing as Unit 4's own
        # test_world_state_rows_are_never_mutated_by_reset: a scenario
        # pinned to an older world_state_id keeps a valid, unmutated
        # reference no matter how many resets follow - Scenario itself
        # doesn't exist until Phase 3, so this proves it at the
        # world_state-row level, extended here to the reset operation.
        seed_initial_world_state_and_clock(session)
        held_id = _root(session).id
        reset_simulation(session)
        reset_simulation(session)
        held = session.get(WorldState, held_id)
        assert held is not None
        assert held.kind == WorldStateKind.CLEAN_BASELINE


class TestUnseededClockGuard:
    # Security review of this unit: current_world_state_id can only be None
    # through a repair/migration edge case, never through this module's own
    # normal path — simulated directly rather than via a real downgrade/
    # upgrade round-trip, since the point is to prove snapshot/reset fail
    # clearly instead of raising a bare AttributeError, not to reproduce
    # the specific way the pointer could go missing.
    def test_snapshot_raises_a_clear_error_when_the_clock_has_no_current_world_state(
        self, session: Session
    ) -> None:
        seed_initial_world_state_and_clock(session)
        clock = session.get(SimulationClock, 1)
        clock.current_world_state_id = None
        session.flush()
        with pytest.raises(SimulationClockNotSeededError):
            snapshot_simulation(session, label="x")

    def test_reset_raises_a_clear_error_when_the_clock_has_no_current_world_state(
        self, session: Session
    ) -> None:
        seed_initial_world_state_and_clock(session)
        clock = session.get(SimulationClock, 1)
        clock.current_world_state_id = None
        session.flush()
        with pytest.raises(SimulationClockNotSeededError):
            reset_simulation(session)


class TestSeedIsATrueNoOpOnceAlreadySeeded:
    def test_a_no_op_seed_call_never_commits_the_callers_pending_work(
        self, session: Session, owner_dsn: str
    ) -> None:
        # The mid-sequence-commit risk a security review of this unit
        # raised is real only for the single call that performs the actual
        # first-ever seed (see seed_initial_world_state_and_clock's own
        # docstring) — every later call, once a world_state row already
        # exists, hits the early `return` before session.commit() and is a
        # true no-op. Proven directly here via a second, independent
        # connection (not just re-reading the same session, which
        # wouldn't distinguish "committed" from "merely flushed"): an
        # uncommitted pause survives an intervening no-op seed call
        # untouched, because that seed call never reaches session.commit().
        seed_initial_world_state_and_clock(session)  # the real first-ever seed, if not already done
        pause_simulation(session)  # flush-only, not committed by itself
        seed_initial_world_state_and_clock(session)  # already-seeded: a true no-op
        with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
            cur.execute("select status from live.simulation_clock where id = 1")
            (status,) = cur.fetchone()
        assert status == "running"  # the pause was never committed


class TestSingleCleanBaselineRootConstraint:
    # Security review of this unit (migration 0009): a second concurrent
    # caller of seed_initial_world_state_and_clock's check-then-act should
    # never be able to commit a second clean_baseline root — proven here by
    # inserting a second one directly (bypassing the idempotency check
    # entirely, the same way two genuinely concurrent callers would each
    # pass the check before either commits) and confirming the DB itself
    # rejects it.
    def test_a_second_clean_baseline_root_is_rejected_by_the_database(
        self, session: Session
    ) -> None:
        seed_initial_world_state_and_clock(session)
        duplicate = WorldState(
            id=uuid.uuid4(),
            kind=WorldStateKind.CLEAN_BASELINE,
            simulation_date=CLEAN_BASELINE_SIMULATION_DATE,
            seed=CLEAN_BASELINE_SEED,
            label="Duplicate Clean Baseline",
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.flush()
