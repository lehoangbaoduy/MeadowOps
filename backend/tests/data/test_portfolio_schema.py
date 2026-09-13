"""Unit 26 (MEADOWOPS-DOM-020, PRD 6.10): structural DB tests for
`engine.portfolio_artifact` - table existence, the `thread_id` uniqueness
constraint (one reflection per ChatThread), and the immutability trigger.
Mirrors tests/data/test_evaluation_schema.py's own shape exactly.

Every test here runs inside one uncommitted transaction, rolled back at the
end, same pattern as test_evaluation_schema.py.
"""

import psycopg
import pytest


def test_portfolio_artifact_table_exists(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select table_name from information_schema.tables "
            "where table_schema = 'engine' and table_name = 'portfolio_artifact'"
        )
        assert cur.fetchone() == ("portfolio_artifact",)


class _ProbeContext:
    """Creates a scenario + thread + portfolio_artifact inside the caller's
    own transaction, never committed - same shape as
    test_evaluation_schema.py's own _ProbeContext."""

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
            "values (gen_random_uuid(), 'zztest-u26-portfolio-probe', 'stakeholder_request', "
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
            "insert into engine.portfolio_artifact "
            "(id, thread_id, submitted_by_user_id, reflection_what_happened, "
            "reflection_initial_thought, reflection_evidence_that_mattered, "
            "reflection_what_missed, reflection_what_changed_after_pushback, "
            "reflection_what_differently, reflection_skill_improved) "
            "values (gen_random_uuid(), %s, %s, 'a', 'b', 'c', 'd', 'e', 'f', 'g') "
            "returning id",
            (self.thread_id, self.user_id),
        )
        (self.artifact_id,) = cur.fetchone()


def test_one_portfolio_artifact_per_thread(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        probe = _ProbeContext(cur)
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute(
                "insert into engine.portfolio_artifact "
                "(id, thread_id, submitted_by_user_id, reflection_what_happened, "
                "reflection_initial_thought, reflection_evidence_that_mattered, "
                "reflection_what_missed, reflection_what_changed_after_pushback, "
                "reflection_what_differently, reflection_skill_improved) "
                "values (gen_random_uuid(), %s, %s, 'a', 'b', 'c', 'd', 'e', 'f', 'g')",
                (probe.thread_id, probe.user_id),
            )
        conn.rollback()


def test_portfolio_artifact_cannot_be_updated(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        probe = _ProbeContext(cur)
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            cur.execute(
                "update engine.portfolio_artifact set reflection_what_happened = 'edited' "
                "where id = %s",
                (probe.artifact_id,),
            )
        conn.rollback()


def test_portfolio_artifact_cannot_be_deleted(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        probe = _ProbeContext(cur)
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            cur.execute(
                "delete from engine.portfolio_artifact where id = %s", (probe.artifact_id,)
            )
        conn.rollback()


def test_portfolio_artifact_cannot_be_truncated(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        _ProbeContext(cur)
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            cur.execute("truncate engine.portfolio_artifact")
        conn.rollback()


def test_immutability_triggers_are_enabled(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select tgname, tgenabled from pg_trigger "
            "where tgrelid = 'engine.portfolio_artifact'::regclass and not tgisinternal "
            "order by tgname"
        )
        rows = dict(cur.fetchall())
    assert rows == {
        "portfolio_artifact_no_delete": "O",
        "portfolio_artifact_no_truncate": "O",
        "portfolio_artifact_no_update": "O",
    }
