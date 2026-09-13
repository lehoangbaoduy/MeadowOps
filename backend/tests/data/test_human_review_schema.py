"""Unit 26 (MEADOWOPS-DOM-020, PRD 6.6 step 11, ER-3/ER-4/ER-6): structural
DB tests for `engine.human_review` - table existence, the `evaluation_id`
uniqueness constraint, the verdict/overridden_recommendation CHECK
constraint (edge case #29), and the immutability trigger. Mirrors
tests/data/test_evaluation_schema.py's own shape exactly.

Every test here runs inside one uncommitted transaction, rolled back at the
end, same pattern as test_evaluation_schema.py.
"""

import psycopg
import pytest


def test_human_review_table_exists(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select table_name from information_schema.tables "
            "where table_schema = 'engine' and table_name = 'human_review'"
        )
        assert cur.fetchone() == ("human_review",)


class _ProbeContext:
    """Creates a scenario + thread + evaluation + human_review inside the
    caller's own transaction, never committed - same shape as
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
            "values (gen_random_uuid(), 'zztest-u26-probe', 'stakeholder_request', "
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

        cur.execute(
            "insert into engine.human_review "
            "(id, evaluation_id, submitted_by_user_id, reviewer_name, verdict, "
            "tier_assessment_notes, overridden_recommendation) "
            "values (gen_random_uuid(), %s, %s, 'zztest reviewer', 'agree', 'looks right', null) "
            "returning id",
            (self.evaluation_id, self.user_id),
        )
        (self.human_review_id,) = cur.fetchone()


def test_verdict_column_rejects_a_value_outside_the_enum(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        probe = _ProbeContext(cur)
        with pytest.raises(psycopg.errors.InvalidTextRepresentation):
            cur.execute(
                "insert into engine.human_review "
                "(id, evaluation_id, submitted_by_user_id, reviewer_name, verdict, "
                "tier_assessment_notes) "
                "values (gen_random_uuid(), %s, %s, 'r', 'not_a_real_verdict', 'n')",
                (probe.evaluation_id, probe.user_id),
            )
        conn.rollback()


def test_one_human_review_per_evaluation(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        probe = _ProbeContext(cur)
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute(
                "insert into engine.human_review "
                "(id, evaluation_id, submitted_by_user_id, reviewer_name, verdict, "
                "tier_assessment_notes) "
                "values (gen_random_uuid(), %s, %s, 'r', 'agree', 'n')",
                (probe.evaluation_id, probe.user_id),
            )
        conn.rollback()


def test_agree_verdict_rejects_a_non_null_overridden_recommendation(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        probe = _ProbeContext(cur)
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "insert into engine.human_review "
                "(id, evaluation_id, submitted_by_user_id, reviewer_name, verdict, "
                "tier_assessment_notes, overridden_recommendation) "
                "values (gen_random_uuid(), gen_random_uuid(), %s, 'r', 'agree', 'n', 'stretch')",
                (probe.user_id,),
            )
        conn.rollback()
        del probe


def test_override_verdict_requires_a_non_null_overridden_recommendation(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute("select id from live.\"user\" limit 1")
        row = cur.fetchone()
        if row is None:
            pytest.skip("no live.user row available (auth_seed not run)")
        (user_id,) = row
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "insert into engine.human_review "
                "(id, evaluation_id, submitted_by_user_id, reviewer_name, verdict, "
                "tier_assessment_notes) "
                "values (gen_random_uuid(), gen_random_uuid(), %s, 'r', 'override', 'n')",
                (user_id,),
            )
        conn.rollback()


def test_override_verdict_with_a_recommendation_is_accepted(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        probe = _ProbeContext(cur)
        cur.execute(
            "insert into engine.scenario "
            "(id, title, scenario_type, competency_cluster, difficulty_tier, "
            "source, ground_truth, status, created_by) "
            "values (gen_random_uuid(), 'zztest-u26-probe-2', 'stakeholder_request', "
            "'communication', 'foundational', 'manual', '{}'::jsonb, 'draft', %s) "
            "returning id",
            (probe.user_id,),
        )
        (scenario_id,) = cur.fetchone()
        cur.execute(
            "insert into chat.chat_thread (id, scenario_id, persona) "
            "values (gen_random_uuid(), %s, 'cfo') returning id",
            (scenario_id,),
        )
        (thread_id,) = cur.fetchone()
        cur.execute(
            "insert into engine.evaluation "
            "(id, thread_id, prompt_version, strengths, gaps, evidence, "
            "senior_analyst_pushback, final_verdict, suggested_next_skill_focus, "
            "difficulty_recommendation, raw_response) "
            "values (gen_random_uuid(), %s, 'draft_evaluation/v1', 's', 'g', 'e', "
            "'p', 'v', 'f', 'standard', '{}') returning id",
            (thread_id,),
        )
        (evaluation_id,) = cur.fetchone()
        cur.execute(
            "insert into engine.human_review "
            "(id, evaluation_id, submitted_by_user_id, reviewer_name, verdict, "
            "tier_assessment_notes, overridden_recommendation) "
            "values (gen_random_uuid(), %s, %s, 'r', 'override', 'n', 'stretch') returning id",
            (evaluation_id, probe.user_id),
        )
        assert cur.fetchone() is not None
        conn.rollback()


def test_human_review_cannot_be_updated(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        probe = _ProbeContext(cur)
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            cur.execute(
                "update engine.human_review set tier_assessment_notes = 'edited' where id = %s",
                (probe.human_review_id,),
            )
        conn.rollback()


def test_human_review_cannot_be_deleted(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        probe = _ProbeContext(cur)
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            cur.execute(
                "delete from engine.human_review where id = %s", (probe.human_review_id,)
            )
        conn.rollback()


def test_human_review_cannot_be_truncated(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        _ProbeContext(cur)
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            cur.execute("truncate engine.human_review")
        conn.rollback()


def test_immutability_triggers_are_enabled(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select tgname, tgenabled from pg_trigger "
            "where tgrelid = 'engine.human_review'::regclass and not tgisinternal "
            "order by tgname"
        )
        rows = dict(cur.fetchall())
    assert rows == {
        "human_review_no_delete": "O",
        "human_review_no_truncate": "O",
        "human_review_no_update": "O",
    }
