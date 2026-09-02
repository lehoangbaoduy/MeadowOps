"""Tests for the Query Playground statement classifier (PRD 5.9, line 372).

PRD line 214 requires destructive statements to be caught "even when chained
in a multi-statement submission, so a destructive statement can't slip
through hidden behind a harmless one" - so the adversarial cases here (CTEs,
comments, string-literal semicolons, dollar-quoted bodies, EXPLAIN) matter
more than the straightforward single-statement cases.
"""

from app.domain.query_classifier import (
    ClassifiedStatement,
    StatementType,
    classify_statement,
    classify_submission,
    requires_confirmation,
    split_statements,
)


class TestClassifyStatementReads:
    def test_classifies_plain_select_as_read(self) -> None:
        assert classify_statement("SELECT 1") is StatementType.READ

    def test_classifies_cte_wrapping_select_as_read(self) -> None:
        sql = "WITH cte AS (SELECT 1) SELECT * FROM cte"
        assert classify_statement(sql) is StatementType.READ

    def test_classifies_plain_explain_of_select_as_read(self) -> None:
        assert classify_statement("EXPLAIN SELECT * FROM x") is StatementType.READ

    def test_classifies_plain_explain_of_delete_as_read_since_it_never_executes(
        self,
    ) -> None:
        # EXPLAIN without ANALYZE only prints a plan; Postgres never runs the
        # underlying statement, so this is genuinely safe despite the DELETE.
        assert classify_statement("EXPLAIN DELETE FROM x") is StatementType.READ


class TestClassifyStatementWrites:
    def test_classifies_insert_as_write(self) -> None:
        assert classify_statement("INSERT INTO x VALUES (1)") is StatementType.WRITE

    def test_classifies_update_as_write(self) -> None:
        assert classify_statement("UPDATE x SET a = 1") is StatementType.WRITE

    def test_classifies_delete_as_write(self) -> None:
        assert classify_statement("DELETE FROM x WHERE id = 1") is StatementType.WRITE

    def test_classifies_create_table_as_write(self) -> None:
        assert (
            classify_statement("CREATE TEMP TABLE t (a int)") is StatementType.WRITE
        )

    def test_classifies_drop_table_as_write(self) -> None:
        assert classify_statement("DROP TABLE x") is StatementType.WRITE

    def test_classifies_alter_table_as_write(self) -> None:
        assert (
            classify_statement("ALTER TABLE x ADD COLUMN a int")
            is StatementType.WRITE
        )

    def test_classifies_cte_wrapping_delete_as_write(self) -> None:
        # The discriminating case: a naive `startswith("WITH")` or first-token
        # check would misclassify this as read because the statement opens
        # with a CTE, but the CTE's own body is irrelevant - what matters is
        # the DML keyword the CTE is feeding into.
        sql = (
            "WITH cte AS (SELECT id FROM x) "
            "DELETE FROM y WHERE id IN (SELECT id FROM cte)"
        )
        assert classify_statement(sql) is StatementType.WRITE

    def test_classifies_write_hidden_inside_cte_body_as_write(self) -> None:
        # The other, more dangerous direction (security review, Unit 9): a
        # data-modifying CTE whose OUTER statement is a plain SELECT. This is
        # real, executable Postgres - the DELETE inside the CTE body runs to
        # completion - but sqlparse's own get_type() only inspects the outer
        # keyword and reports "SELECT". A naive get_type()-only classifier
        # would wrongly call this a read requiring no confirmation.
        sql = "WITH cte AS (DELETE FROM x RETURNING *) SELECT * FROM cte"
        assert classify_statement(sql) is StatementType.WRITE

    def test_classifies_update_hidden_inside_cte_body_as_write(self) -> None:
        sql = "WITH cte AS (UPDATE x SET a=1 RETURNING *) SELECT * FROM cte"
        assert classify_statement(sql) is StatementType.WRITE

    def test_classifies_insert_hidden_inside_cte_body_as_write(self) -> None:
        sql = "WITH cte AS (INSERT INTO x VALUES (1) RETURNING *) SELECT * FROM cte"
        assert classify_statement(sql) is StatementType.WRITE

    def test_classifies_write_hidden_in_one_of_several_ctes_as_write(self) -> None:
        # A second CTE in the WITH list is where the write hides; the final
        # SELECT only references the harmless one.
        sql = (
            "WITH cte1 AS (DELETE FROM x RETURNING *), cte2 AS (SELECT 1) "
            "SELECT * FROM cte2"
        )
        assert classify_statement(sql) is StatementType.WRITE

    def test_classifies_select_into_as_write(self) -> None:
        # SELECT ... INTO creates and populates a table - a write, even
        # though sqlparse's get_type() reports "SELECT" for it and doesn't
        # tag INTO as a DML/DDL keyword the way it tags DELETE/UPDATE/INSERT.
        sql = "SELECT * INTO new_table FROM old_table"
        assert classify_statement(sql) is StatementType.WRITE

    def test_classifies_delete_preceded_by_line_comment_as_write(self) -> None:
        assert (
            classify_statement("-- comment\nDELETE FROM x WHERE id=1")
            is StatementType.WRITE
        )

    def test_classifies_update_preceded_by_block_comment_as_write(self) -> None:
        assert (
            classify_statement("/* block */ UPDATE x SET a=1") is StatementType.WRITE
        )

    def test_classifies_bare_explain_analyze_delete_as_write(self) -> None:
        # EXPLAIN ANALYZE actually executes the statement.
        assert (
            classify_statement("EXPLAIN ANALYZE DELETE FROM x") is StatementType.WRITE
        )

    def test_classifies_parenthesized_explain_analyze_delete_as_write(self) -> None:
        assert (
            classify_statement("EXPLAIN (ANALYZE) DELETE FROM x")
            is StatementType.WRITE
        )

    def test_classifies_parenthesized_explain_analyze_with_extra_options_as_write(
        self,
    ) -> None:
        assert (
            classify_statement("EXPLAIN (ANALYZE, BUFFERS) DELETE FROM x")
            is StatementType.WRITE
        )

    def test_classifies_bare_explain_analyse_british_spelling_delete_as_write(
        self,
    ) -> None:
        # Postgres accepts both spellings and both execute the wrapped
        # statement (security review, Unit 9 - the American-only regex let
        # this slip through as a false READ).
        assert (
            classify_statement("EXPLAIN ANALYSE DELETE FROM x") is StatementType.WRITE
        )

    def test_classifies_parenthesized_explain_analyse_british_spelling_as_write(
        self,
    ) -> None:
        assert (
            classify_statement("EXPLAIN (ANALYSE) DELETE FROM x")
            is StatementType.WRITE
        )


class TestClassifyStatementUnknownFailsSafe:
    def test_classifies_blank_input_as_unknown(self) -> None:
        assert classify_statement("   ") is StatementType.UNKNOWN

    def test_classifies_unrecognized_session_command_as_unknown_not_read(
        self,
    ) -> None:
        # SET/SHOW/COPY/VACUUM/CALL/GRANT/etc. aren't SELECT, and sqlparse
        # doesn't recognize their statement type - the fail-safe default must
        # land on UNKNOWN (non-read), never READ.
        for sql in ("SET search_path = public", "CALL my_proc()", "VACUUM x"):
            assert classify_statement(sql) is StatementType.UNKNOWN, sql

    def test_classifies_dollar_quoted_do_block_as_unknown_not_read(self) -> None:
        # A DO block can hide arbitrary writes inside $$ ... $$; sqlparse
        # can't classify it, so it must fail toward "needs confirmation".
        sql = "DO $$ BEGIN DELETE FROM x; END; $$"
        assert classify_statement(sql) is StatementType.UNKNOWN


class TestSplitStatementsRespectsQuotingAndComments:
    def test_splits_on_top_level_semicolons(self) -> None:
        assert split_statements("SELECT 1; DROP TABLE x") == [
            "SELECT 1;",
            "DROP TABLE x",
        ]

    def test_does_not_split_on_semicolon_inside_string_literal(self) -> None:
        sql = "SELECT '; DROP TABLE x;' AS s"
        assert split_statements(sql) == [sql]

    def test_does_not_split_on_semicolons_inside_dollar_quoted_body(self) -> None:
        sql = "SELECT 1; DO $$ BEGIN DELETE FROM x; END; $$; SELECT 2"
        assert split_statements(sql) == [
            "SELECT 1;",
            "DO $$ BEGIN DELETE FROM x; END; $$;",
            "SELECT 2",
        ]

    def test_does_not_split_on_semicolon_inside_line_comment(self) -> None:
        sql = "SELECT * FROM x -- ; DELETE FROM y"
        assert split_statements(sql) == [sql]

    def test_drops_blank_and_semicolon_only_fragments(self) -> None:
        assert split_statements("  ; SELECT 1;  ") == ["SELECT 1;"]

    def test_blank_submission_splits_to_no_statements(self) -> None:
        assert split_statements("   ") == []


class TestClassifySubmissionAndRequiresConfirmation:
    def test_classify_submission_returns_one_entry_per_statement(self) -> None:
        result = classify_submission("SELECT 1; DROP TABLE x")
        assert result == [
            ClassifiedStatement(sql="SELECT 1;", statement_type=StatementType.READ),
            ClassifiedStatement(sql="DROP TABLE x", statement_type=StatementType.WRITE),
        ]

    def test_requires_confirmation_false_for_pure_read_submission(self) -> None:
        assert requires_confirmation("SELECT 1; SELECT 2") is False

    def test_requires_confirmation_true_when_any_statement_is_write(self) -> None:
        # This is PRD line 214's exact scenario: a destructive statement
        # hidden behind a harmless leading SELECT.
        assert requires_confirmation("SELECT 1; DROP TABLE x") is True

    def test_requires_confirmation_true_for_cte_wrapped_delete(self) -> None:
        sql = "WITH cte AS (SELECT id FROM x) DELETE FROM y WHERE id IN (SELECT id FROM cte)"
        assert requires_confirmation(sql) is True

    def test_requires_confirmation_true_when_unknown(self) -> None:
        assert requires_confirmation("VACUUM x") is True

    def test_requires_confirmation_false_for_blank_submission(self) -> None:
        assert requires_confirmation("   ") is False
