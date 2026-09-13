"""Unit 28 (MEADOWOPS-API-005, PRD 6.12/S1-FR-14): composite index backing
the admin query-log view's ORDER BY (submitted_at DESC, id DESC).

`live.query_log` (migration 0016) had no index beyond its PK. Unit 19's own
GET /api/v1/query/history stays cheap regardless (WHERE user_id = :id,
LIMIT 50 — a handful of rows per user), but Unit 28's admin route
(app.api.admin_query_log) does an unfiltered JOIN + sort + paginate (limit
up to 500) over the whole table, which only ever grows as every Query
Playground submission logs a row. A plain ascending btree on
(submitted_at, id) serves the DESC/DESC ordering equally well via a
backward index scan — no need for a descending index or op class.

Code review of this unit flagged the missing index; adding it here rather
than folding it into 0016 since that migration is long since applied.

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-09
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_query_log_submitted_at_id",
        "query_log",
        ["submitted_at", "id"],
        schema="live",
    )


def downgrade() -> None:
    op.drop_index("ix_query_log_submitted_at_id", table_name="query_log", schema="live")
