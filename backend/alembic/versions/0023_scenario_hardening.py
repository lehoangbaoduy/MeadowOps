"""Unit 30 (MEADOWOPS-DOM-030, PRD 9.2 edge case catalog hardening sweep).

`world_state_id` (PRD 4.2 line 130: "every scenario stores its...
world_state_id"). A soft/provenance reference, not a ForeignKeyConstraint -
same reasoning as `source_exception_flag_id` (0015's own docstring):
world_state rows are an append-only audit trail
(app.services.simulation_clock_ops), never mutated in place, so a plain
nullable UUID column is enough to pin a scenario to the state it was
created against. Closes catalog row 7 ("reset triggered while a scenario
is active" - the in-flight scenario's own world_state_id stays valid and
unmutated no matter how many resets follow, since reset always inserts a
new world_state row rather than touching any existing one).

This migration originally also added `ux_scenario_single_active`, a
partial unique index on `status` filtered to `WHERE status = 'active'`,
meant to enforce catalog row 19 ("only one scenario active at a time") at
the DB level. Reverted before this migration ever shipped: ScenarioStatus
has no transition out of "active" (app.domain.scenario.VALID_TRANSITIONS)
- it's the permanent resting state for every scenario that has ever run,
by design (activation was deliberately left as this unit's own lifecycle
terminus - see that module's docstring). A blanket "at most one row with
status=active, ever, across all of history" is a much stronger guarantee
than the PRD's actual ask, and broke real, correct multi-scenario history
(app.services.evaluation_service's difficulty-tier tests, the QA harness's
callback scenario). Row 19 is instead enforced app-side in
activate_scenario (app.services.scenario_service) against whether another
active scenario's work is still in flight (has no completed
chat.chat_thread) - see that function's own docstring, and B13 in
prd/MeadowOps_progress.md for the deferred "real" terminal-status fix this
punts on.

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scenario",
        sa.Column("world_state_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="engine",
    )


def downgrade() -> None:
    op.drop_column("scenario", "world_state_id", schema="engine")
