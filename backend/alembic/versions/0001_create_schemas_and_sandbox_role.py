"""Create live/reporting/engine/sandbox schemas and the restricted sandbox role.

Unit MEADOWOPS-INFRA-001. Implements PRD 5.9's hard, database-enforced
permission boundary and 4.1's schema layout up front (DD-7,
prd/MeadowOps_progress.md), so later units never retrofit grants after
domain tables already exist:

- live      Subsystem 1 operational + Decision & Event Ledger tables.
- reporting Deliberately-lagged shadow copies of `live` (PRD 4.1, SR-2).
- engine    Subsystem 2 supporting tables (scenario, evaluation, portfolio...).
- sandbox   Nightly/on-demand refreshed replica of `live` only, for the SQL
            Query Playground (PRD 5.9). The only schema `meadowops_sandbox`
            can reach.

Default privileges are set at the schema level so any table a later unit
adds to live/reporting/engine is unreachable by the sandbox role without a
separate grant per table (tested: test_a_table_created_later_in_live_schema
_is_still_blocked_by_default).

Revision ID: 0001
Revises:
Create Date: 2026-09-01
"""

import os
import re
from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_HEX_PASSWORD = re.compile(r"^[0-9a-f]{16,64}$")


def _sandbox_role_password() -> str:
    """Read from env rather than hardcoding (CONST-SEC-001). Validated as
    hex-only before DDL interpolation (CREATE ROLE has no bind-parameter
    form) as defense in depth, even though this value is server-generated,
    never user input."""
    password = os.environ["MEADOWOPS_SANDBOX_ROLE_PASSWORD"]
    if not _HEX_PASSWORD.fullmatch(password):
        raise ValueError(
            "MEADOWOPS_SANDBOX_ROLE_PASSWORD must be a hex string "
            "(as generated for .env) before it can be safely used in DDL"
        )
    return password


def upgrade() -> None:
    password = _sandbox_role_password()

    op.execute("CREATE SCHEMA IF NOT EXISTS live")
    op.execute("CREATE SCHEMA IF NOT EXISTS reporting")
    op.execute("CREATE SCHEMA IF NOT EXISTS engine")
    op.execute("CREATE SCHEMA IF NOT EXISTS sandbox")

    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'meadowops_sandbox') THEN "
        f"CREATE ROLE meadowops_sandbox LOGIN PASSWORD '{password}' "
        "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT; "
        "END IF; END $$;"
    )

    # Deny-by-default: no privileges on the operational/reporting/engine
    # schemas for anyone but the owner role. PUBLIC is revoked explicitly
    # rather than relying on Postgres defaults, so the boundary is visible
    # in the migration, not implicit.
    for schema in ("live", "reporting", "engine"):
        op.execute(f"REVOKE ALL ON SCHEMA {schema} FROM PUBLIC")
        op.execute(f"REVOKE ALL ON SCHEMA {schema} FROM meadowops_sandbox")
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} "
            f"REVOKE ALL ON TABLES FROM meadowops_sandbox"
        )

    # sandbox schema: the one place meadowops_sandbox may read, write, and
    # create scratch objects — free-form SQL practice (PRD 5.9), consequence-
    # free because nothing here is live data.
    #
    # NOTE for whichever unit implements the nightly/on-demand sandbox
    # refresh job: this CREATE grant means meadowops_sandbox can pre-plant
    # same-named tables/functions in the sandbox schema. The refresh job
    # must NOT run as the `meadowops` bootstrap role with an ambient
    # search_path touching `sandbox` (classic search_path privilege
    # escalation, CVE-2018-1058 shape) — it must run as a dedicated
    # non-superuser role, use fully-qualified names or an explicit
    # search_path excluding `sandbox`, and any function it defines must
    # pin its own search_path. Flagged by security review of this unit.
    op.execute("GRANT USAGE, CREATE ON SCHEMA sandbox TO meadowops_sandbox")
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE meadowops IN SCHEMA sandbox "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO meadowops_sandbox"
    )

    # Hard cap on concurrent sandbox connections — a DoS control that must
    # live at the role level. Per-query statement_timeout is USERSET (the
    # sandbox role can override its own session's timeout), so it is not a
    # real enforcement boundary and is deliberately NOT relied on here; the
    # Query Playground's execution path (a later unit) must itself apply a
    # server-side timeout per query, not just an ALTER ROLE default.
    op.execute("ALTER ROLE meadowops_sandbox CONNECTION LIMIT 5")

    # General hardening: close the default `public` schema loophole, both
    # halves — CREATE (object planting) and USAGE (visibility). PG15+
    # already omits the CREATE grant from initdb, but stating it explicitly
    # keeps the boundary visible in the migration rather than implicit in
    # server defaults across whatever Postgres version deployment ends up
    # on. Residual risk, accepted and documented rather than "fixed": raw
    # pg_catalog (pg_class/pg_tables/pg_namespace) is not permission-
    # filtered like information_schema is, so meadowops_sandbox can still
    # observe that a table/column *name* exists in live/reporting/engine
    # even with zero USAGE — never its contents. Same root cause covers
    # LISTEN/NOTIFY (channel-scoped, not schema-scoped, in stock Postgres).
    # Accepted for Build & Test: MPS is simulated company data, not real
    # PII, and no code path uses pg_notify on live-schema events. Revisit
    # (sandbox in a separate database, not just a separate schema) before
    # any real sensitive data or NOTIFY-based signaling is introduced.
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    op.execute("REVOKE USAGE ON SCHEMA public FROM PUBLIC")


def downgrade() -> None:
    op.execute("GRANT USAGE ON SCHEMA public TO PUBLIC")
    op.execute("GRANT CREATE ON SCHEMA public TO PUBLIC")
    op.execute("ALTER ROLE meadowops_sandbox CONNECTION LIMIT -1")
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE meadowops IN SCHEMA sandbox "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM meadowops_sandbox"
    )
    op.execute("REVOKE USAGE, CREATE ON SCHEMA sandbox FROM meadowops_sandbox")
    # Schema (and anything meadowops_sandbox came to own within it) must go
    # before the role — DROP ROLE fails if the role still owns objects.
    op.execute("DROP SCHEMA IF EXISTS sandbox CASCADE")
    op.execute("DROP OWNED BY meadowops_sandbox")
    op.execute("DROP ROLE IF EXISTS meadowops_sandbox")
    op.execute("DROP SCHEMA IF EXISTS engine CASCADE")
    op.execute("DROP SCHEMA IF EXISTS reporting CASCADE")
    op.execute("DROP SCHEMA IF EXISTS live CASCADE")
