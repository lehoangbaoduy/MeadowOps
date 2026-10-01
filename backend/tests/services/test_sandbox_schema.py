"""Unit 36 (MEADOWOPS-DOM-024): the Query Playground's schema viewer - which
tables, columns and relationships the Analyst can actually query. Derived
from the same SANDBOX_MIRRORED_TABLES allowlist the sandbox refresh uses,
so the viewer can never advertise a table the sandbox role cannot read.
"""

import app.db  # noqa: F401 - registers every table on Base.metadata
from app.db.base import Base
from app.services.sandbox_refresh import SANDBOX_MIRRORED_TABLES
from app.services.sandbox_schema import describe_sandbox_schema


class TestDescribeSandboxSchema:
    def test_lists_exactly_the_mirrored_tables(self) -> None:
        schema = describe_sandbox_schema(Base.metadata)
        assert {t.name for t in schema.tables} == set(SANDBOX_MIRRORED_TABLES)

    def test_tables_are_sorted_by_name(self) -> None:
        names = [t.name for t in describe_sandbox_schema(Base.metadata).tables]
        assert names == sorted(names)

    def test_every_table_is_qualified_with_the_sandbox_schema(self) -> None:
        for table in describe_sandbox_schema(Base.metadata).tables:
            assert table.qualified_name == f"sandbox.{table.name}"

    def test_never_exposes_non_queryable_schemas(self) -> None:
        names = {t.name for t in describe_sandbox_schema(Base.metadata).tables}
        assert "scenario" not in names
        assert "chat_message" not in names
        assert "user" not in names

    def test_describes_columns_with_type_nullability_and_primary_key(self) -> None:
        product = next(
            t for t in describe_sandbox_schema(Base.metadata).tables if t.name == "product"
        )
        by_name = {c.name: c for c in product.columns}
        assert by_name["id"].is_primary_key is True
        assert by_name["sku"].is_primary_key is False
        assert by_name["sku"].nullable is False
        assert by_name["unit_cost"].type.startswith("NUMERIC")

    def test_includes_foreign_key_relationships_between_queryable_tables(self) -> None:
        relationships = describe_sandbox_schema(Base.metadata).relationships
        assert any(
            r.from_table == "purchase_order_line"
            and r.from_column == "product_id"
            and r.to_table == "product"
            and r.to_column == "id"
            for r in relationships
        )

    def test_relationships_only_reference_queryable_tables(self) -> None:
        schema = describe_sandbox_schema(Base.metadata)
        names = {t.name for t in schema.tables}
        for relationship in schema.relationships:
            assert relationship.from_table in names
            assert relationship.to_table in names
