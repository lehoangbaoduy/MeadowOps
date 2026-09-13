"""Unit 25 (MEADOWOPS-DOM-019, PRD 6.8/ER-6): structural DB tests for
`engine.evaluation` - table existence, the `thread_id` uniqueness
constraint (one Evaluation per ChatThread), and the immutability trigger.
Mirrors tests/data/test_chat_schema.py's own shape exactly (security
review of this unit: that file's own precedent - proving the trigger is
independently enabled on the shared dev database, not just "unconditional
when enabled" - applies identically here, and was missing until this file).

Every test here runs inside one uncommitted transaction, rolled back at the
end, same pattern as test_chat_schema.py.
"""

import psycopg
import pytest


def test_evaluation_table_exists(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select table_name from information_schema.tables "
            "where table_schema = 'engine' and table_name = 'evaluation'"
        )
        assert cur.fetchone() == ("evaluation",)


class _ProbeContext:
    """Creates a scenario + thread + evaluation inside the caller's own
    transaction, never committed - same shape as test_chat_schema.py's own
    _ProbeContext."""

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
            "values (gen_random_uuid(), 'zztest-u25-probe', 'stakeholder_request', "
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
            "insert into engine.evaluation "
            "(id, thread_id, prompt_version, strengths, gaps, evidence, "
            "senior_analyst_pushback, final_verdict, suggested_next_skill_focus, "
            "difficulty_recommendation, raw_response) "
            "values (gen_random_uuid(), %s, 'draft_evaluation/v1', 's', 'g', 'e', "
            "'p', 'v', 'f', 'standard', '{}') returning id",
            (self.thread_id,),
        )
        (self.evaluation_id,) = cur.fetchone()


def test_difficulty_recommendation_column_rejects_a_value_outside_the_enum(
    owner_dsn: str,
) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        probe = _ProbeContext(cur)
        with pytest.raises(psycopg.errors.InvalidTextRepresentation):
            cur.execute(
                "insert into engine.evaluation "
                "(id, thread_id, prompt_version, strengths, gaps, evidence, "
                "senior_analyst_pushback, final_verdict, suggested_next_skill_focus, "
                "difficulty_recommendation, raw_response) "
                "values (gen_random_uuid(), %s, 'draft_evaluation/v1', 's', 'g', 'e', "
                "'p', 'v', 'f', 'not_a_real_tier', '{}')",
                (probe.thread_id,),
            )
        conn.rollback()


def test_one_evaluation_per_thread(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        probe = _ProbeContext(cur)
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute(
                "insert into engine.evaluation "
                "(id, thread_id, prompt_version, strengths, gaps, evidence, "
                "senior_analyst_pushback, final_verdict, suggested_next_skill_focus, "
                "difficulty_recommendation, raw_response) "
                "values (gen_random_uuid(), %s, 'draft_evaluation/v1', 's', 'g', 'e', "
                "'p', 'v', 'f', 'standard', '{}')",
                (probe.thread_id,),
            )
        conn.rollback()


def test_evaluation_cannot_be_updated(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        probe = _ProbeContext(cur)
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            cur.execute(
                "update engine.evaluation set final_verdict = 'edited' where id = %s",
                (probe.evaluation_id,),
            )
        conn.rollback()


def test_evaluation_cannot_be_deleted(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        probe = _ProbeContext(cur)
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            cur.execute(
                "delete from engine.evaluation where id = %s", (probe.evaluation_id,)
            )
        conn.rollback()


def test_evaluation_cannot_be_truncated(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        _ProbeContext(cur)
        # Unit 26 (MEADOWOPS-DOM-020): engine.human_review now FK-references
        # engine.evaluation, so a plain `TRUNCATE engine.evaluation` alone
        # no longer even reaches this table's own trigger - Postgres refuses
        # it outright at the FK-check stage (FeatureNotSupported, "cannot
        # truncate a table referenced in a foreign key constraint"), before
        # any BEFORE TRUNCATE trigger runs. Both tables must be named in the
        # same statement for Postgres to proceed far enough to fire the
        # trigger this test actually means to prove.
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            cur.execute("truncate engine.evaluation, engine.human_review")
        conn.rollback()


def test_immutability_triggers_are_enabled(owner_dsn: str) -> None:
    """Security review of this unit: proves the trigger is durably enabled
    on the shared dev database, not just "unconditional when enabled" - a
    test fixture elsewhere in this suite (tests/api/test_chat_api.py's
    scenario_id/rich_scenario_id fixtures) uses the documented ALTER TABLE
    ... DISABLE TRIGGER escape hatch for its own cleanup and re-enables it
    afterward; this is the independent check that a failure partway
    through that dance hasn't silently left the one mechanism enforcing
    PRD 6.9 ER-6 turned off."""
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select tgname, tgenabled from pg_trigger "
            "where tgrelid = 'engine.evaluation'::regclass and not tgisinternal "
            "order by tgname"
        )
        rows = dict(cur.fetchall())
    assert rows == {
        "evaluation_no_delete": "O",
        "evaluation_no_truncate": "O",
        "evaluation_no_update": "O",
    }
