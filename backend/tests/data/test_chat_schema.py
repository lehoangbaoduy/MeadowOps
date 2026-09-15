"""Unit 21a (MEADOWOPS-DOM-014, PRD 6.13/§7/Appendix B): structural DB tests
for the chat delivery substrate — schema/table existence, the
(scenario_id, persona) uniqueness constraint (DD-25's "one thread per
persona per scenario, for its whole life"), and the immutability trigger
(PRD 6.13/ER-6). Sandbox-role exclusion lives in
tests/infra/test_sandbox_boundary.py, alongside every other schema's own
boundary proof.

Every test here runs inside one uncommitted transaction, rolled back at the
end (same pattern tests/data/test_ledger_schema.py already uses) — nothing
here ever needs a persistent probe-row cleanup step, including the
immutability tests, since even a caught exception's partial effects vanish
on rollback.
"""

import importlib.util
import os
from pathlib import Path

import psycopg
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def test_chat_schema_and_tables_exist(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select table_name from information_schema.tables "
            "where table_schema = 'chat' order by table_name"
        )
        # chat_thread_read_state (migration 0019, Unit 21) added alongside
        # the two Unit 21a originals — unread-thread badge state, S1-FR-15.
        # notification (migration 0024, Unit 30a) — deadline-tracking
        # notifications, PRD 6.1/B12. chat_thread_draft (migration 0025,
        # Unit 30b) — per-(thread, user) composer draft, catalog row 31.
        # chat_attachment (migration 0026, Unit 30c) — Analyst-uploaded
        # file metadata, S1-FR-15/PRD 347/380.
        assert {row[0] for row in cur.fetchall()} == {
            "chat_message",
            "chat_thread",
            "chat_thread_read_state",
            "notification",
            "chat_thread_draft",
            "chat_attachment",
        }


class _ProbeContext:
    """Creates a scenario + thread + message inside the caller's own
    transaction, never committed — a real live.user row already exists
    from auth seeding (app.services.auth_seed), reused rather than
    inserted, since `user.email` is unique and this runs against the
    shared dev database."""

    def __init__(self, cur: psycopg.Cursor) -> None:
        cur.execute("select id from live.\"user\" limit 1")
        row = cur.fetchone()
        if row is None:
            pytest.skip("no live.user row available (auth_seed not run)")
        (self.user_id,) = row

        cur.execute(
            "insert into engine.scenario "
            "(id, title, scenario_type, competency_cluster, difficulty_tier, "
            "source, ground_truth, status, created_by) "
            "values (gen_random_uuid(), 'zztest-u21a-probe', 'stakeholder_request', "
            "'communication', 'foundational', 'manual', '{}'::jsonb, 'draft', %s) "
            "returning id",
            (self.user_id,),
        )
        (self.scenario_id,) = cur.fetchone()

        cur.execute(
            "insert into chat.chat_thread (id, scenario_id, persona) "
            "values (gen_random_uuid(), %s, 'cfo') returning id",
            (self.scenario_id,),
        )
        (self.thread_id,) = cur.fetchone()

        cur.execute(
            "insert into chat.chat_message "
            "(id, thread_id, sender_user_id, sender_role, body) "
            "values (gen_random_uuid(), %s, %s, 'admin', 'zztest probe message') "
            "returning id",
            (self.thread_id, self.user_id),
        )
        (self.message_id,) = cur.fetchone()


def test_persona_column_rejects_a_value_outside_the_enum(owner_dsn: str) -> None:
    """Code review of this unit: an earlier version of this test relied on
    an ambient `engine.scenario` row and silently skipped (never actually
    exercising the constraint it's named for) whenever the shared dev
    database happened to have none — the same "test that could never fail
    regardless of what it checks" shape this project has hit before
    (app.services.sandbox_refresh's own module docstring names the prior
    instance). Builds its own probe scenario instead, same as every other
    test below."""
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        probe = _ProbeContext(cur)
        with pytest.raises(psycopg.errors.InvalidTextRepresentation):
            cur.execute(
                "insert into chat.chat_thread (id, scenario_id, persona) "
                "values (gen_random_uuid(), %s, 'not_a_real_persona')",
                (probe.scenario_id,),
            )
        conn.rollback()


def test_one_thread_per_scenario_and_persona_pair(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        probe = _ProbeContext(cur)
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute(
                "insert into chat.chat_thread (id, scenario_id, persona) "
                "values (gen_random_uuid(), %s, 'cfo')",
                (probe.scenario_id,),
            )
        conn.rollback()


def test_chat_message_cannot_be_updated(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        probe = _ProbeContext(cur)
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            cur.execute(
                "update chat.chat_message set body = 'edited' where id = %s",
                (probe.message_id,),
            )
        conn.rollback()


def test_chat_message_cannot_be_deleted(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        probe = _ProbeContext(cur)
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            cur.execute(
                "delete from chat.chat_message where id = %s", (probe.message_id,)
            )
        conn.rollback()


def test_chat_message_cannot_be_truncated(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        _ProbeContext(cur)
        # Unit 30c (MEADOWOPS-UI-005): chat_attachment.message_id now FKs
        # to chat_message, so a plain (non-CASCADE) TRUNCATE is rejected by
        # Postgres's own referential-integrity guard ("cannot truncate a
        # table referenced in a foreign key constraint") before the
        # statement ever reaches the BEFORE TRUNCATE trigger this test
        # exists to prove. CASCADE lets the statement past that guard so it
        # reaches the trigger, which still blocks it exactly as before -
        # this test is otherwise unchanged.
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            cur.execute("truncate chat.chat_message cascade")
        conn.rollback()


def test_immutability_triggers_are_enabled(owner_dsn: str) -> None:
    """Security review of this unit: proves the trigger is durably enabled
    on the shared dev database, not just "unconditional when enabled" (the
    property the tests above prove) — a test fixture elsewhere in this
    suite uses the documented ALTER TABLE ... DISABLE TRIGGER escape hatch
    for its own cleanup and re-enables it afterward; this is the
    independent check that a failure partway through that dance (or any
    other DISABLE left uncommitted-back) hasn't silently left the one
    mechanism enforcing PRD 6.13/ER-6 turned off."""
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select tgname, tgenabled from pg_trigger "
            "where tgrelid = 'chat.chat_message'::regclass and not tgisinternal "
            "order by tgname"
        )
        rows = dict(cur.fetchall())
    # 'O' = origin (fires in normal 'origin'/'local' session_replication_role
    # mode, i.e. always for ordinary application traffic) — Postgres's own
    # default and what CREATE TRIGGER sets, never overridden anywhere in
    # this codebase.
    assert rows == {
        "chat_message_no_delete": "O",
        "chat_message_no_truncate": "O",
        "chat_message_no_update": "O",
    }


def _load_migration_0027():
    """alembic/versions/0027_....py can't be a normal dotted import (Python
    module names can't start with a digit) - loaded by file path instead.
    Raises (FileNotFoundError via the loader) before that file exists,
    which is what makes this test a real regression test tied to the
    actual migration rather than to a hand-duplicated copy of its SQL."""
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0027_fix_chat_message_sender_role_drift.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0027", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_0027_repairs_a_missing_sender_role_column() -> None:
    """B15: regression test for a real production incident. The live
    Railway/Neon database had `chat.chat_message` missing its `sender_role`
    column entirely (`psycopg.errors.UndefinedColumn` on every real send)
    even though alembic reported revision 0026 as fully applied there -
    migration 0018 already includes this column, so alembic's own bookkeeping
    gave no signal anything was wrong (see migration 0027's own docstring for
    the full incident and root-cause theory).

    Executes migration 0027's own upgrade() function for real (a standalone
    Alembic Operations context bound to this connection - the documented
    way to drive Alembic operations outside of `alembic upgrade`), against
    the real chat.chat_message table, inside one uncommitted transaction -
    reproducing production's exact drifted state (zero rows, missing
    column) without permanently losing this shared dev database's own
    existing rows, which the rollback at the end restores untouched.
    Deleting those rows first to reach that zero-rows state needs the same
    immutability-trigger-disable escape hatch this project's other fixtures
    already use for committed teardown (e.g. tests/api/test_chat_api.py) -
    here, inside a transaction that's never committed, re-enabling the
    trigger and restoring the deleted rows both happen for free via
    rollback rather than by undoing them by hand.
    """
    migration = _load_migration_0027()

    engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
    conn = engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("alter table chat.chat_message disable trigger chat_message_no_delete"))
        conn.execute(text("delete from chat.chat_message"))
        conn.execute(text("alter table chat.chat_message enable trigger chat_message_no_delete"))
        conn.execute(text("alter table chat.chat_message drop column sender_role"))

        result = conn.execute(
            text(
                "select column_name from information_schema.columns "
                "where table_schema = 'chat' and table_name = 'chat_message' "
                "and column_name = 'sender_role'"
            )
        )
        assert result.fetchone() is None  # drift reproduced

        mc = MigrationContext.configure(conn)
        with Operations.context(mc):
            migration.upgrade()

        result = conn.execute(
            text(
                "select is_nullable from information_schema.columns "
                "where table_schema = 'chat' and table_name = 'chat_message' "
                "and column_name = 'sender_role'"
            )
        )
        assert result.fetchone() == ("NO",)

        # Idempotency: re-running against an already-correct column (the
        # real state in every environment except the drifted production
        # database) must not raise.
        with Operations.context(mc):
            migration.upgrade()
    finally:
        trans.rollback()
        conn.close()
