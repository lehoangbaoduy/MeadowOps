"""World state no-self-parent check (code review of MEADOWOPS-DOM-002).

Hand-written ALTER, same rationale as 0005: mirrors decision_event's
ck_decision_event_no_self_supersede, which exists for the identical reason
(a self-referencing lineage FK forms a 1-cycle unless a same-statement CHECK
blocks it — verified empirically that, absent this, a row could be inserted
as its own parent).

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-01
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE live.world_state "
        "ADD CONSTRAINT ck_world_state_no_self_parent CHECK (id != parent_id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE live.world_state DROP CONSTRAINT ck_world_state_no_self_parent")
