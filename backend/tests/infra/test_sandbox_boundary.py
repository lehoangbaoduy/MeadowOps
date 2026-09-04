"""Unit 1 (MEADOWOPS-INFRA-001): proves the SQL Query Playground's hard
permission boundary (PRD 5.9, 8.4) at the database level, not just by
asserting the role config exists.

Edge case catalog (PRD 9.2), SQL Query Playground row 26:
"Attempted write against a table outside the sandbox schema" ->
"Rejected at the database permission level."

Unit 9 (MEADOWOPS-DOMAIN-003) extends this file rather than re-proving the
mechanism: the tests above already establish the general boundary (including
against tables that don't exist yet, via `future_probe`) using synthetic
probe tables created by U1 before any real domain schema existed. The
`TestRealSchemaTables` class below re-runs the same boundary check against
the actual `live.product` / `live.supplier` / `live.warehouse` /
`live.carrier` tables that hold real baseline-seeded rows (Unit 5's
generator; created by migration 0002, Unit 2) - closing PRD line 351/572's
"must be verified with an actual permission test" against the schema as it
exists today, not just as it existed at Unit 1. `purchase_order` is checked
for INSERT-blocked separately, not via the seeded-rows parametrize list: the
baseline generator seeds only master data, not transactional facts, so the
table is legitimately empty until a later unit's scheduled order flow (U13)
populates it - a "has seeded rows" assertion against it would be
permanently false rather than meaningful (Unit 10 found this the hard way:
a single row that appeared seeded was actually a leaked, uncleaned-up test
row from `tests/data/test_core_schema.py`, now fixed - see that file).
"""

import psycopg
import pytest


def test_live_reporting_and_engine_schemas_exist(owner_dsn: str) -> None:
    with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select schema_name from information_schema.schemata "
            "where schema_name in ('live', 'reporting', 'engine', 'sandbox') "
            "order by schema_name"
        )
        found = {row[0] for row in cur.fetchall()}
    assert found == {"engine", "live", "reporting", "sandbox"}


def test_sandbox_role_can_read_and_write_within_sandbox_schema(sandbox_dsn: str) -> None:
    with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "create table if not exists sandbox.boundary_probe_rw "
            "(id integer primary key)"
        )
        try:
            cur.execute("insert into sandbox.boundary_probe_rw (id) values (1) "
                        "on conflict (id) do nothing")
            cur.execute("select id from sandbox.boundary_probe_rw where id = 1")
            assert cur.fetchone() == (1,)
        finally:
            cur.execute("drop table if exists sandbox.boundary_probe_rw")


# DDL committed by the owner connection below is deliberately NOT rolled
# back: a probe table created inside an uncommitted transaction is invisible
# to the separate sandbox_dsn connection each test uses to attempt access
# (Postgres MVCC — another session can't see an uncommitted CREATE TABLE at
# all, so it would fail with UndefinedTable rather than the
# InsufficientPrivilege each test exists to prove). Committed, then dropped
# in a `finally` so a leaked table can't survive even an assertion failure —
# code review of Unit 4 traced migrations 0002-0004's broken fresh-database
# bootstrap back to exactly these tables committing probe tables with no
# cleanup at all (DD-10).
def test_sandbox_role_cannot_write_to_live_table(owner_dsn: str, sandbox_dsn: str) -> None:
    with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "create table if not exists live.boundary_probe "
            "(id integer primary key)"
        )
    try:
        with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("insert into live.boundary_probe (id) values (1)")
    finally:
        with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("drop table if exists live.boundary_probe")


def test_sandbox_role_cannot_read_live_table(owner_dsn: str, sandbox_dsn: str) -> None:
    with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "create table if not exists live.boundary_probe "
            "(id integer primary key)"
        )
    try:
        with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("select * from live.boundary_probe")
    finally:
        with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("drop table if exists live.boundary_probe")


def test_sandbox_role_cannot_reach_engine_schema(owner_dsn: str, sandbox_dsn: str) -> None:
    with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "create table if not exists engine.boundary_probe "
            "(id integer primary key)"
        )
    try:
        with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("select * from engine.boundary_probe")
    finally:
        with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("drop table if exists engine.boundary_probe")


def test_sandbox_role_cannot_reach_chat_schema(owner_dsn: str, sandbox_dsn: str) -> None:
    """Unit 21a (MEADOWOPS-DOM-014): chat is PRD §7's second named exception
    to the no-direct-cross-subsystem-access rule, but that exception is
    "each subsystem's own API layer reads/writes it" — the sandbox role
    (arbitrary user-submitted SQL, PRD 5.9) has no more business reaching
    it than it does `live`/`reporting`/`engine`. Same boundary-probe
    pattern as those three schemas below — proven even though
    `_live_table_names()` already excludes `chat` by construction (it isn't
    `live`), matching 8.4's "verified with an actual permission test, not
    just asserted" standard rather than trusting that filter alone."""
    with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "create table if not exists chat.boundary_probe (id integer primary key)"
        )
    try:
        with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("select * from chat.boundary_probe")
    finally:
        with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("drop table if exists chat.boundary_probe")


def test_sandbox_role_cannot_reach_real_chat_message_table(
    owner_dsn: str, sandbox_dsn: str
) -> None:
    """Same boundary against the real table (not a synthetic probe),
    mirroring TestRealSchemaTables' own reasoning below for live."""
    with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("select * from chat.chat_message")


def test_a_table_created_later_in_chat_schema_is_still_blocked_by_default(
    owner_dsn: str, sandbox_dsn: str
) -> None:
    """Mirrors test_a_table_created_later_in_live_schema_is_still_blocked_
    by_default below — proves migration 0018's own ALTER DEFAULT PRIVILEGES
    line (not just the schema-level REVOKE) actually covers a table added
    to `chat` after this migration ran, the same guarantee `live` already
    has."""
    with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("drop table if exists chat.future_probe")
        cur.execute("create table chat.future_probe (id integer primary key)")
    try:
        with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("select * from chat.future_probe")
    finally:
        with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("drop table if exists chat.future_probe")


def test_sandbox_role_cannot_reach_reporting_schema(owner_dsn: str, sandbox_dsn: str) -> None:
    with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "create table if not exists reporting.boundary_probe "
            "(id integer primary key)"
        )
    try:
        with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("select * from reporting.boundary_probe")
    finally:
        with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("drop table if exists reporting.boundary_probe")


def test_sandbox_role_cannot_create_objects_outside_sandbox_schema(sandbox_dsn: str) -> None:
    with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("create table live.sneaky (id integer)")


def test_sandbox_role_cannot_create_objects_in_public_schema(sandbox_dsn: str) -> None:
    with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("create table public.sneaky (id integer)")


def test_sandbox_role_has_connection_limit(sandbox_dsn: str) -> None:
    with psycopg.connect(sandbox_dsn) as conn, conn.cursor() as cur:
        cur.execute("select rolconnlimit from pg_roles where rolname = current_user")
        (limit,) = cur.fetchone()
    assert limit == 5


def test_sandbox_role_has_no_superuser_or_role_creation_privileges(sandbox_dsn: str) -> None:
    with psycopg.connect(sandbox_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select rolsuper, rolcreatedb, rolcreaterole "
            "from pg_roles where rolname = current_user"
        )
        rolsuper, rolcreatedb, rolcreaterole = cur.fetchone()
    assert (rolsuper, rolcreatedb, rolcreaterole) == (False, False, False)


def test_a_table_created_later_in_live_schema_is_still_blocked_by_default(
    owner_dsn: str, sandbox_dsn: str
) -> None:
    """Default privileges must cover tables that don't exist yet — future
    domain tables (Unit 2+) inherit the boundary automatically, it isn't
    re-granted table by table."""
    with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("drop table if exists live.future_probe")
        cur.execute("create table live.future_probe (id integer primary key)")
    try:
        with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("select * from live.future_probe")
    finally:
        with psycopg.connect(owner_dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("drop table if exists live.future_probe")


class TestRealSchemaTables:
    """Same boundary, proven against real tables with real seeded rows
    instead of synthetic probe tables - see module docstring."""

    @pytest.mark.parametrize("table", ["product", "supplier", "warehouse", "carrier"])
    def test_real_table_has_seeded_rows_to_make_the_block_meaningful(
        self, owner_dsn: str, table: str
    ) -> None:
        # If this were 0, the SELECT-blocked test below would pass just as
        # easily against an empty table - confirm there's actually something
        # to leak before trusting the negative result. `purchase_order` is
        # deliberately excluded here - see module docstring.
        with psycopg.connect(owner_dsn) as conn, conn.cursor() as cur:
            cur.execute(f"select count(*) from live.{table}")
            (count,) = cur.fetchone()
        assert count > 0

    @pytest.mark.parametrize("table", ["product", "supplier", "warehouse", "carrier"])
    def test_sandbox_role_cannot_select_from_real_live_table(
        self, sandbox_dsn: str, table: str
    ) -> None:
        with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute(f"select * from live.{table}")

    def test_sandbox_role_cannot_select_from_real_purchase_order_table(
        self, sandbox_dsn: str
    ) -> None:
        # No "has seeded rows" precondition here (see module docstring) -
        # InsufficientPrivilege is a table-level ACL check Postgres raises
        # before touching any row, so it's just as meaningful against a
        # currently-empty table as a populated one.
        with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("select * from live.purchase_order")

    def test_sandbox_role_cannot_insert_into_real_purchase_order_table(
        self, sandbox_dsn: str
    ) -> None:
        with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute(
                    "insert into live.purchase_order (id) values (gen_random_uuid())"
                )

    def test_sandbox_role_cannot_update_real_product_table(
        self, sandbox_dsn: str
    ) -> None:
        with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("update live.product set sku = sku")

    def test_sandbox_role_cannot_delete_from_real_supplier_table(
        self, sandbox_dsn: str
    ) -> None:
        with psycopg.connect(sandbox_dsn, autocommit=True) as conn, conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("delete from live.supplier")
