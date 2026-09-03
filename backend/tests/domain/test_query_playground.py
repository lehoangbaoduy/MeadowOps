"""Unit 19 (MEADOWOPS-DOMAIN-010, spec MEADOWOPS-DOM-012): pure domain logic
for the Query Playground's two lifecycles plus its row-limiting/statement-
summary helpers. State-machine cases below are the exact set harness-os's
generate_tests enumerated from the domain spec's stateMachines.
"""

import pytest

from app.domain.query_classifier import ClassifiedStatement, StatementType
from app.domain.query_playground import (
    MAX_RESULT_ROWS,
    QuerySubmissionStatus,
    SandboxRefreshStatus,
    can_transition_refresh,
    can_transition_submission,
    overall_statement_type,
    truncate_rows,
)

SUBMISSION_CASES = [
    ("received", "confirmation_required", True),
    ("received", "executing", True),
    ("received", "success", False),
    ("received", "error", False),
    ("received", "timed_out", False),
    ("received", "cancelled", False),
    ("confirmation_required", "received", False),
    ("confirmation_required", "executing", True),
    ("confirmation_required", "success", False),
    ("confirmation_required", "error", False),
    ("confirmation_required", "timed_out", False),
    ("confirmation_required", "cancelled", True),
    ("executing", "received", False),
    ("executing", "confirmation_required", False),
    ("executing", "success", True),
    ("executing", "error", True),
    ("executing", "timed_out", True),
    ("executing", "cancelled", False),
    ("success", "received", False),
    ("success", "confirmation_required", False),
    ("success", "executing", False),
    ("success", "error", False),
    ("success", "timed_out", False),
    ("success", "cancelled", False),
    ("error", "received", False),
    ("error", "confirmation_required", False),
    ("error", "executing", False),
    ("error", "success", False),
    ("error", "timed_out", False),
    ("error", "cancelled", False),
    ("timed_out", "received", False),
    ("timed_out", "confirmation_required", False),
    ("timed_out", "executing", False),
    ("timed_out", "success", False),
    ("timed_out", "error", False),
    ("timed_out", "cancelled", False),
    ("cancelled", "received", False),
    ("cancelled", "confirmation_required", False),
    ("cancelled", "executing", False),
    ("cancelled", "success", False),
    ("cancelled", "error", False),
    ("cancelled", "timed_out", False),
]

REFRESH_CASES = [
    ("running", "swapped", True),
    ("running", "complete", False),
    ("running", "failed", True),
    ("swapped", "running", False),
    ("swapped", "complete", True),
    ("swapped", "failed", True),
    ("complete", "running", False),
    ("complete", "swapped", False),
    ("complete", "failed", False),
    ("failed", "running", False),
    ("failed", "swapped", False),
    ("failed", "complete", False),
]


@pytest.mark.parametrize("from_status,to_status,expected", SUBMISSION_CASES)
def test_can_transition_submission(from_status: str, to_status: str, expected: bool) -> None:
    assert can_transition_submission(from_status, to_status) is expected


@pytest.mark.parametrize("from_status,to_status,expected", REFRESH_CASES)
def test_can_transition_refresh(from_status: str, to_status: str, expected: bool) -> None:
    assert can_transition_refresh(from_status, to_status) is expected


def test_query_submission_status_values_match_generated_state_names() -> None:
    assert {s.value for s in QuerySubmissionStatus} == {
        "received",
        "confirmation_required",
        "executing",
        "success",
        "error",
        "timed_out",
        "cancelled",
    }


def test_sandbox_refresh_status_values_match_generated_state_names() -> None:
    assert {s.value for s in SandboxRefreshStatus} == {
        "running",
        "swapped",
        "complete",
        "failed",
    }


class TestTruncateRows:
    def test_returns_all_rows_untruncated_when_under_limit(self) -> None:
        rows = [{"id": i} for i in range(3)]
        result, truncated = truncate_rows(rows, limit=10)
        assert result == rows
        assert truncated is False

    def test_truncates_and_flags_when_over_limit(self) -> None:
        rows = [{"id": i} for i in range(10)]
        result, truncated = truncate_rows(rows, limit=5)
        assert result == rows[:5]
        assert truncated is True

    def test_exactly_at_limit_is_not_truncated(self) -> None:
        rows = [{"id": i} for i in range(5)]
        result, truncated = truncate_rows(rows, limit=5)
        assert result == rows
        assert truncated is False

    def test_default_limit_is_max_result_rows_constant(self) -> None:
        rows = [{"id": i} for i in range(MAX_RESULT_ROWS + 1)]
        result, truncated = truncate_rows(rows)
        assert len(result) == MAX_RESULT_ROWS
        assert truncated is True


class TestOverallStatementType:
    def test_empty_submission_is_unknown(self) -> None:
        assert overall_statement_type([]) == "unknown"

    def test_all_read_is_read(self) -> None:
        classified = [
            ClassifiedStatement(sql="select 1", statement_type=StatementType.READ),
            ClassifiedStatement(sql="select 2", statement_type=StatementType.READ),
        ]
        assert overall_statement_type(classified) == "read"

    def test_any_write_makes_it_write(self) -> None:
        classified = [
            ClassifiedStatement(sql="select 1", statement_type=StatementType.READ),
            ClassifiedStatement(sql="delete from x", statement_type=StatementType.WRITE),
        ]
        assert overall_statement_type(classified) == "write"

    def test_unknown_without_any_write_is_unknown(self) -> None:
        classified = [
            ClassifiedStatement(sql="select 1", statement_type=StatementType.READ),
            ClassifiedStatement(sql="???", statement_type=StatementType.UNKNOWN),
        ]
        assert overall_statement_type(classified) == "unknown"

    def test_write_takes_priority_over_unknown(self) -> None:
        classified = [
            ClassifiedStatement(sql="???", statement_type=StatementType.UNKNOWN),
            ClassifiedStatement(sql="delete from x", statement_type=StatementType.WRITE),
        ]
        assert overall_statement_type(classified) == "write"
