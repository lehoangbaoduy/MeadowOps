"""Unit 19 (MEADOWOPS-DOM-012, PRD 5.9): request/response schemas for the
Query Playground's execution and history routes.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.query_playground import QuerySubmissionStatus


class QuerySubmitRequest(BaseModel):
    sql: str = Field(min_length=1)
    confirmed: bool = False


class QueryStatementPreview(BaseModel):
    sql: str
    statement_type: str


class QueryConfirmationRequiredResponse(BaseModel):
    status: str = QuerySubmissionStatus.CONFIRMATION_REQUIRED.value
    statements: list[QueryStatementPreview]


class QueryExecuteResponse(BaseModel):
    status: str
    columns: list[str]
    rows: list[dict]
    row_count: int
    truncated: bool
    duration_ms: int
    error_message: str | None


class QueryLogRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_id: uuid.UUID
    query_text: str
    statement_type: str
    result_status: str
    row_count: int | None
    duration_ms: int | None
    error_message: str | None
    submitted_at: datetime


class AdminQueryLogRead(QueryLogRead):
    """Unit 28 (MEADOWOPS-API-005, PRD 6.12/S1-FR-14): adds the submitting
    user's email for the admin cross-user view. A separate schema from
    QueryLogRead rather than adding `user_email` there — QueryLogRead is
    also returned by the Analyst-facing GET /api/v1/query/history, which has
    no business exposing another user's identity via a widened field."""

    user_email: str


class SandboxRefreshResponse(BaseModel):
    status: str
    tables_mirrored: int
    started_at: datetime
    completed_at: datetime
    error: str | None
