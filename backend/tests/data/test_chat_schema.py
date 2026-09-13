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

import psycopg
import pytest


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
