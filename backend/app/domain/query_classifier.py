"""Statement-type classification for the SQL Query Playground's soft boundary
(PRD 5.9, S1-FR-13/14, spec MEADOWOPS-DOMAIN-003).

Every statement submitted to the Playground must be classified read
(SELECT-only) vs. write (DML/DDL/anything else) so the UI can require an
explicit confirmation before running anything destructive - including a
destructive statement hidden behind a harmless one in a multi-statement
submission (PRD line 214: "even when chained ... so a destructive statement
can't slip through hidden behind a harmless one").

Anything this module cannot confidently prove is read-only classifies as
StatementType.UNKNOWN, which requires_confirmation() treats the same as
WRITE. A false "needs confirmation" is an inconvenience; a false "safe to
run" is a data-loss bug - so the default always fails toward confirmation.

sqlparse's own Statement.get_type() is NOT enough on its own: it reports
only the outermost/final DML keyword, so `WITH cte AS (DELETE FROM x
RETURNING *) SELECT * FROM cte` - a real, executable, data-modifying CTE -
reports as "SELECT". classify_statement() instead flattens every token in
the parsed statement and checks for ANY DML/DDL keyword anywhere in the
tree (security review, Unit 9): a write hidden inside a CTE body, or a
second CTE in a WITH list, is caught even though the outer statement reads
as SELECT. `SELECT ... INTO` (table-creating, not flagged as DML/DDL by
sqlparse at all) is checked for separately as a required WRITE case for
the same reason.

This is the classifier only. The editor, results table, confirmation dialog
UI, query-history logging, statement timeout, and row limits are Phase 2
work (PRD line 484, unit MEADOWOPS-DOMAIN-010) and are out of scope here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

import sqlparse
from sqlparse.tokens import DDL, DML, Keyword


class StatementType(str, Enum):
    READ = "read"
    WRITE = "write"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ClassifiedStatement:
    sql: str
    statement_type: StatementType


_EXPLAIN_KEYWORD_RE = re.compile(r"^\s*EXPLAIN\b", re.IGNORECASE)
_EXPLAIN_PAREN_OPTIONS_RE = re.compile(r"^\s*EXPLAIN\s*\(([^)]*)\)", re.IGNORECASE)
# ANALYZE/ANALYSE: Postgres accepts both spellings (security review, Unit 9 -
# the American-only spelling let `EXPLAIN ANALYSE DELETE ...` slip through as
# a false READ, even though EXPLAIN ANALY[SZ]E always executes the wrapped
# statement).
_ANALYZE_WORD_RE = re.compile(r"\bANALY[SZ]E\b", re.IGNORECASE)
_EXPLAIN_BARE_ANALYZE_RE = re.compile(r"^\s*EXPLAIN\s+ANALY[SZ]E\b", re.IGNORECASE)


def _classify_explain(stripped: str) -> StatementType:
    paren_match = _EXPLAIN_PAREN_OPTIONS_RE.match(stripped)
    if paren_match:
        analyzes = bool(_ANALYZE_WORD_RE.search(paren_match.group(1)))
        remainder = stripped[paren_match.end() :]
    else:
        bare_match = _EXPLAIN_BARE_ANALYZE_RE.match(stripped)
        if bare_match:
            analyzes = True
            remainder = stripped[bare_match.end() :]
        else:
            # Plain EXPLAIN (no options, no bare ANALYZE) - strip only the
            # keyword itself. Legacy option syntax we don't recognize here
            # (e.g. "EXPLAIN VERBOSE ...") is still safe to call read: plain
            # EXPLAIN never executes the underlying statement regardless of
            # what other modifiers follow it.
            analyzes = False
            remainder = stripped[_EXPLAIN_KEYWORD_RE.match(stripped).end() :]

    if not analyzes:
        return StatementType.READ
    return classify_statement(remainder)


def classify_statement(sql: str) -> StatementType:
    """Classifies a single SQL statement.

    Callers with a possibly multi-statement submission should use
    classify_submission instead - this does not split on ';'.
    """
    stripped = sql.strip()
    if not stripped:
        return StatementType.UNKNOWN

    if _EXPLAIN_KEYWORD_RE.match(stripped):
        return _classify_explain(stripped)

    parsed = sqlparse.parse(stripped)
    if not parsed:
        return StatementType.UNKNOWN

    stmt = parsed[0]
    stmt_type = stmt.get_type()
    tokens = list(stmt.flatten())

    # Every DML/DDL keyword anywhere in the tree, not just the outer
    # statement's - a CTE body (`WITH cte AS (DELETE FROM x ...) SELECT ...`)
    # tokenizes its inner DELETE as Keyword.DML too, even though get_type()
    # only reports the outer SELECT.
    dml_ddl_values = {tok.value.upper() for tok in tokens if tok.ttype in (DML, DDL)}

    # `SELECT ... INTO ...` creates and populates a table - sqlparse tags
    # INTO as a plain Keyword, not DML/DDL, so it isn't caught by the check
    # above and needs its own look.
    has_select_into = stmt_type == "SELECT" and any(
        tok.ttype is Keyword and tok.value.upper() == "INTO" for tok in tokens
    )

    if stmt_type == "SELECT" and dml_ddl_values <= {"SELECT"} and not has_select_into:
        return StatementType.READ
    if stmt_type == "UNKNOWN" and not dml_ddl_values:
        return StatementType.UNKNOWN
    return StatementType.WRITE


def split_statements(sql: str) -> list[str]:
    """Splits a submission into individual statement strings.

    Delegates to sqlparse.split(), which tokenizes rather than naively
    splitting on ';' - it correctly leaves semicolons inside string literals,
    comments, and dollar-quoted bodies (e.g. `DO $$ ... ; ... $$`) alone.
    Blank and semicolon-only fragments are dropped.
    """
    return [
        stmt
        for stmt in (raw.strip() for raw in sqlparse.split(sql))
        if stmt and stmt != ";"
    ]


def classify_submission(sql: str) -> list[ClassifiedStatement]:
    """Classifies every statement in a (possibly multi-statement) submission."""
    return [
        ClassifiedStatement(sql=stmt, statement_type=classify_statement(stmt))
        for stmt in split_statements(sql)
    ]


def requires_confirmation(sql: str) -> bool:
    """True if any statement in the submission is not a plain read.

    This is the soft boundary itself (PRD 5.9): the caller must show the
    confirmation dialog before executing the submission whenever this
    returns True. A submission with zero statements (blank input) has
    nothing to confirm.
    """
    return any(
        classified.statement_type is not StatementType.READ
        for classified in classify_submission(sql)
    )
