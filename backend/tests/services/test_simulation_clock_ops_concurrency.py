"""Unit 12a (MEADOWOPS-DOM-005): proves advance_simulation's (and every
other clock op's) SELECT ... FOR UPDATE lock on the simulation_clock
singleton row actually serializes concurrent callers (PRD 9.2 row 6)
rather than racing. Real Postgres, two separate connections/transactions -
the same rigor as Unit 10's sabotage-and-restore: proving the lock has real
teeth, not just reading the code and trusting FOR UPDATE does what it's
supposed to.

Security review of this unit caught a real gap in the first version of this
file: it proved Postgres row-locking semantics on live.simulation_clock via
a hand-written raw psycopg SELECT ... FOR UPDATE, but never actually called
into app.services.simulation_clock_ops — so it would have stayed green even
if .with_for_update() were accidentally removed from _lock_clock(). Fixed
two ways: the cross-connection test below now drives both the holder and
the waiter through the real advance_simulation() function on two genuinely
separate SQLAlchemy Sessions/connections, and a second, cheap unit-level
test independently confirms _lock_clock()'s own statement is compiled with
FOR UPDATE - a fast, non-flaky check that would catch the same regression
even faster than the threaded test would.

Both threads roll back their own session's transaction at the end (never
commit) so this test never leaves the shared dev database's real clock in
a mutated state - same discipline as test_simulation_clock_ops.py.
"""

import os
import threading
import time

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.services.simulation_clock_ops import (
    _lock_clock,
    advance_simulation,
    seed_initial_world_state_and_clock,
)


@pytest.fixture
def session():
    engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_lock_clock_issues_a_select_for_update(session: Session) -> None:
    seed_initial_world_state_and_clock(session)
    captured_statements: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        captured_statements.append(statement)

    event.listen(session.bind, "before_cursor_execute", _capture)
    try:
        _lock_clock(session)
    finally:
        event.remove(session.bind, "before_cursor_execute", _capture)

    assert captured_statements, "_lock_clock issued no SQL at all"
    assert any("FOR UPDATE" in stmt.upper() for stmt in captured_statements), (
        f"none of _lock_clock's statements included FOR UPDATE: {captured_statements}"
    )


def test_a_second_caller_of_advance_simulation_blocks_until_the_first_releases(
    session: Session,
) -> None:
    seed_initial_world_state_and_clock(session)

    lock_acquired = threading.Event()
    release_lock = threading.Event()
    timings: dict[str, float] = {}

    def holder() -> None:
        engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
        with Session(engine) as holder_session:
            # advance_simulation() itself issues the SELECT ... FOR UPDATE
            # (via _lock_clock) and the UPDATE, all within this still-open,
            # uncommitted transaction — the row lock is held until rollback
            # below, exactly like a real caller who hasn't committed yet.
            advance_simulation(holder_session, days=1)
            lock_acquired.set()
            release_lock.wait(timeout=5)
            holder_session.rollback()
        engine.dispose()

    def waiter() -> None:
        lock_acquired.wait(timeout=5)
        engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
        with Session(engine) as waiter_session:
            timings["waiter_started_at"] = time.monotonic()
            advance_simulation(waiter_session, days=1)
            timings["waiter_acquired_at"] = time.monotonic()
            waiter_session.rollback()
        engine.dispose()

    t1 = threading.Thread(target=holder)
    t2 = threading.Thread(target=waiter)
    t1.start()
    assert lock_acquired.wait(timeout=5), "holder never acquired the lock"
    t2.start()
    time.sleep(0.3)  # give the waiter a real chance to block on the row lock
    release_lock.set()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert "waiter_acquired_at" in timings, "waiter never acquired the lock"
    assert timings["waiter_acquired_at"] - timings["waiter_started_at"] >= 0.25, (
        "waiter's advance_simulation() call returned too quickly - it should "
        "have blocked on the holder's still-open FOR UPDATE lock, not raced "
        "past it"
    )
