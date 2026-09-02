"""Unit 4 (MEADOWOPS-DOM-002): world_state + simulation_clock tables
(PRD 4.2).

Edge case catalog (PRD 9.2) rows covered here:
- #6 Concurrent snapshot/reset operations serialized safely (world_state
  inserts are independent rows — no shared mutable state to corrupt;
  simulation_clock's singleton row is the actual contended resource, tested
  in test_simulation_clock_concurrency.py).
- #7 Reset triggered while a scenario is active: at this unit's scope
  (Scenario doesn't exist until Phase 3), the testable proxy is that
  world_state rows are never updated or deleted once created — a "reset"
  always inserts a new row, so anything already holding an older
  world_state_id keeps a valid reference no matter how many resets follow.
"""

import psycopg
import pytest


def test_world_state_and_simulation_clock_tables_exist(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select table_name from information_schema.tables "
            "where table_schema = 'live' and table_name in ('world_state', 'simulation_clock')"
        )
        found = {row[0] for row in cur.fetchall()}
    assert found == {"world_state", "simulation_clock"}


def test_simulation_clock_is_a_true_singleton(owner_dsn: str) -> None:
    """A second row (any id other than 1) must be rejected — this is what
    makes 'the current simulated business date' unambiguous. Rolled back,
    not autocommitted (code review of this unit: the autocommit version
    permanently committed a row keyed to the real calendar date via
    `current_date`, which then silently defeated the Unit 5 seeder's
    ON CONFLICT DO NOTHING for the singleton row — the same leaking-test
    class of bug test_ledger_schema.py's rollback tests already guard
    against for the ledger table)."""
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "insert into live.simulation_clock (id, simulation_date, status) "
            "values (1, '2026-01-01', 'running') "
            "on conflict (id) do nothing"
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "insert into live.simulation_clock (id, simulation_date, status) "
                "values (2, '2026-01-01', 'running')"
            )
        conn.rollback()


def test_world_state_rows_are_never_mutated_by_reset(owner_dsn: str) -> None:
    """Proxy for PRD 9.2 row 7 at this unit's scope: two resets never
    change a prior world_state row's simulation_date once created. Rolled
    back, not autocommitted — same leaking-test class of bug as above
    (code review of this unit: 14 rows had accumulated in the shared dev DB
    from repeated autocommitted runs of this test).

    'first' row uses kind='snapshot', not 'clean_baseline': Unit 12a added
    ux_world_state_single_clean_baseline_root (a partial unique index on
    kind='clean_baseline' AND parent_id IS NULL), and the real dev database
    now has a genuine clean_baseline root row (Unit 12a's own seed) that
    this synthetic row would collide with. This test was never asserting
    anything about the 'clean_baseline' kind specifically — any kind value
    proves the same append-only-immutability point."""
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "insert into live.world_state (id, kind, simulation_date, seed, label) "
            "values (gen_random_uuid(), 'snapshot', '2026-01-01', 'seed-1', 'first') "
            "returning id"
        )
        (first_id,) = cur.fetchone()
        cur.execute(
            "insert into live.world_state (id, kind, simulation_date, seed, label) "
            "values (gen_random_uuid(), 'reset', '2026-02-01', 'seed-2', 'second reset')"
        )
        cur.execute(
            "select simulation_date from live.world_state where id = %s", (first_id,)
        )
        (simulation_date,) = cur.fetchone()
        conn.rollback()
    assert str(simulation_date) == "2026-01-01"


def test_world_state_parent_id_rejects_a_reference_to_a_nonexistent_row(owner_dsn: str) -> None:
    """FK enforcement against a parent_id with no matching row — distinct
    from self-reference, see test_world_state_cannot_be_its_own_parent
    below (code review of this unit: the two were previously conflated
    under one test named for the self-reference case, which this one
    doesn't actually exercise)."""
    with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cur.execute(
                "insert into live.world_state (id, kind, simulation_date, seed, label, parent_id) "
                "values (gen_random_uuid(), 'snapshot', '2026-01-01', 'seed', 'x', gen_random_uuid())"
            )


def test_world_state_cannot_be_its_own_parent(owner_dsn: str) -> None:
    """Code review of this unit: verified empirically that, absent a CHECK,
    a row can reference itself as parent_id within the same INSERT
    statement (an FK is satisfied once the row exists, even self-satisfied)
    — mirrors ck_decision_event_no_self_supersede's rationale for the
    ledger table's own self-referencing lineage column."""
    with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("select gen_random_uuid()")
        (new_id,) = cur.fetchone()
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "insert into live.world_state (id, kind, simulation_date, seed, label, parent_id) "
                "values (%s, 'snapshot', '2026-01-01', 'seed', 'x', %s)",
                (new_id, new_id),
            )


def test_sandbox_role_cannot_reach_world_state_or_clock(owner_dsn: str, sandbox_dsn: str) -> None:
    with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("select * from live.world_state")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("select * from live.simulation_clock")
