"""Unit 3 (MEADOWOPS-DOM-001): Decision & Event Ledger table (PRD 4.4,
Appendix B). Structural DB tests — the transition state machine itself is
tested exhaustively in tests/domain/test_ledger_transitions.py.

Edge case catalog (PRD 9.2) rows covered here:
- #13 Two decisions on the same entity with conflicting outcomes: both
  preserved, no silent overwrite.
"""

import psycopg
import pytest


def test_decision_event_table_exists_in_live_schema(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select table_name from information_schema.tables "
            "where table_schema = 'live' and table_name = 'decision_event'"
        )
        assert cur.fetchone() is not None


def test_status_column_rejects_a_value_outside_the_lifecycle_enum(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InvalidTextRepresentation):
            cur.execute(
                "insert into live.decision_event "
                "(id, record_type, status, entity_type, entity_id, title, "
                "summary, proposed_at) "
                "values (gen_random_uuid(), 'decision', 'not_a_real_status', "
                "'supplier', 'S-004', 'Test', 'Test', now())"
            )


def test_two_decisions_on_the_same_entity_are_both_preserved(owner_dsn: str) -> None:
    """No uniqueness constraint on (entity_type, entity_id) — conflicting
    outcomes about the same entity must coexist, never silently overwrite
    each other (PRD 9.2 row 13)."""
    # Not autocommit: both inserts and the count happen inside one
    # transaction that's explicitly rolled back at the end, so re-running
    # this test never accumulates rows (it isn't a unique-constraint clash
    # like Unit 2's — the count assertion would just silently grow: 2, 4,
    # 6... — caught by actually running this test twice in a row).
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        for outcome, note in (
            ("succeeded", "first decision, worked"),
            ("failed", "second decision, made it worse"),
        ):
            cur.execute(
                "insert into live.decision_event "
                "(id, record_type, status, entity_type, entity_id, title, "
                "summary, proposed_at, outcome, outcome_notes) "
                "values (gen_random_uuid(), 'decision', 'outcome_observed', "
                "'supplier', 'S-CONFLICT-TEST', 'Test decision', 'Test', now(), "
                "%s, %s)",
                (outcome, note),
            )
        cur.execute(
            "select count(*) from live.decision_event where entity_id = 'S-CONFLICT-TEST'"
        )
        (count,) = cur.fetchone()
        conn.rollback()
        assert count == 2


def test_supersedes_id_self_references_decision_event(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cur.execute(
                "insert into live.decision_event "
                "(id, record_type, status, entity_type, entity_id, title, "
                "summary, proposed_at, supersedes_id) "
                "values (gen_random_uuid(), 'decision', 'proposed', 'supplier', "
                "'S-004', 'Test', 'Test', now(), gen_random_uuid())"
            )


def test_entity_id_has_no_hard_foreign_key(owner_dsn: str) -> None:
    """Deliberately a plain string, not an FK to e.g. live.supplier.id —
    deactivating (soft-delete, is_active=false) a supplier must never orphan
    or block a ledger record referencing it (PRD 9.2 row 12, callback
    scenarios). A row referencing a nonexistent/deactivated entity_id must
    insert cleanly. Rolled back, not autocommitted — security review of this
    unit caught the autocommit version permanently leaking a row into the
    shared dev database on every run."""
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "insert into live.decision_event "
            "(id, record_type, status, entity_type, entity_id, title, "
            "summary, proposed_at) "
            "values (gen_random_uuid(), 'decision', 'proposed', 'supplier', "
            "'S-DOES-NOT-EXIST', 'Test', 'Test', now())"
        )
        conn.rollback()


def test_entity_type_rejects_a_value_outside_the_known_set(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InvalidTextRepresentation):
            cur.execute(
                "insert into live.decision_event "
                "(id, record_type, status, entity_type, entity_id, title, "
                "summary, proposed_at) "
                "values (gen_random_uuid(), 'decision', 'proposed', 'suplier', "
                "'S-004', 'Test', 'Test', now())"
            )


def test_decision_event_cannot_supersede_itself(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("select gen_random_uuid()")
        (new_id,) = cur.fetchone()
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "insert into live.decision_event "
                "(id, record_type, status, entity_type, entity_id, title, "
                "summary, proposed_at, supersedes_id) "
                "values (%s, 'decision', 'proposed', 'supplier', 'S-004', "
                "'Test', 'Test', now(), %s)",
                (new_id, new_id),
            )


def test_sandbox_role_cannot_reach_decision_event(owner_dsn: str, sandbox_dsn: str) -> None:
    """Re-confirms Unit 1's default-privilege boundary generalizes to the
    ledger table specifically, since PRD 5.9/8.4 name the ledger explicitly
    as protected, not just 'live' schema tables in general."""
    with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("select * from live.decision_event")
