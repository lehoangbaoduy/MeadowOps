"""Sets meadowops_sandbox's own default search_path to `sandbox` (Unit 19,
MEADOWOPS-DOM-012, PRD 5.9).

Found live, in the browser, testing the Query page: the sandbox role's
search_path defaulted to Postgres's own default ("$user", public), so an
unqualified `select * from product` — the natural way anyone would type a
practice query — failed with "relation does not exist" even though
`sandbox.product` exists and the role can read it. PRD 5.9 frames this
feature as consequence-free, easy open-ended practice; requiring every
statement to be schema-qualified defeats that. This role has zero
privileges on live/reporting/engine regardless of search_path (revoked at
the schema level by migration 0001), so pointing its default search_path at
the one schema it can ever reach adds no new access — it only changes what
an *unqualified* name resolves to for connections authenticating as this
role.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-03
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER ROLE meadowops_sandbox SET search_path = sandbox")


def downgrade() -> None:
    op.execute("ALTER ROLE meadowops_sandbox RESET search_path")
