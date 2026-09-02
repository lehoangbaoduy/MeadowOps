"""Enforce at most one clean_baseline root world_state row (MEADOWOPS-DOM-005,
security review of Unit 12a).

seed_initial_world_state_and_clock() uses check-then-act ("does any
world_state row exist? if not, insert one") rather than an atomic
ON CONFLICT DO NOTHING like app.services.baseline_data.seed_master_data()
does — the reviewer's point being that this function has no live caller yet,
so the race is currently hypothetical, but the DB should still refuse a
second root regardless of which future code path calls this function twice
concurrently. A partial unique index closes it at the source of truth
instead of relying on every future caller to serialize correctly: a losing
racer gets a clean IntegrityError instead of silently committing a second
clean_baseline row, which would permanently break reset_simulation's
scalar_one() root lookup (MultipleResultsFound on every future reset, with
no repair path in the service module).

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-02
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX ux_world_state_single_clean_baseline_root "
        "ON live.world_state ((kind)) "
        "WHERE kind = 'clean_baseline' AND parent_id IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX live.ux_world_state_single_clean_baseline_root")
