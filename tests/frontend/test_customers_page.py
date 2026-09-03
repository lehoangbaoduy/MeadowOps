"""Unit 12c (MEADOWOPS-API-006): orbynadmin's Customers page wired to the
real API (PRD Appendix D.1, Phase 1 checklist item "Pages selected per
Appendix D scaffolded and connected to the real API layer" — narrowed to
Customers only, the one Appendix D page with non-empty real seeded data
available in Phase 1; see the progress doc's B7/DD-17).

Structural checks only, same style as test_template_prep.py /
test_dashboard_skeleton.py — no rendering, no build (npm run build is
this unit's actual correctness gate, run separately, since there's no JS
unit test runner in this repo — DD-17).
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SUBSYSTEM_1 = REPO_ROOT / "frontend/subsystem_1/orbynadmin"
CUSTOMERS_PAGE = SUBSYSTEM_1 / "src/app/(app)/customers/page.tsx"
CUSTOMERS_TABLE = SUBSYSTEM_1 / "src/components/customers-table.tsx"


def test_customers_table_component_exists() -> None:
    assert CUSTOMERS_TABLE.is_file()


def test_customers_page_no_longer_uses_the_empty_state_placeholder() -> None:
    text = CUSTOMERS_PAGE.read_text(encoding="utf-8")
    assert "EmptyState" not in text


def test_customers_page_fetches_from_the_real_admin_api() -> None:
    text = CUSTOMERS_PAGE.read_text(encoding="utf-8")
    assert "listMasterData" in text
    assert '"customers"' in text


def test_customers_table_has_no_write_actions() -> None:
    # S1-FR-12 excludes Customer from admin CRUD (PRD Appendix D.1) —
    # unlike master-data-crud.tsx, this table must never grow an Edit/
    # Deactivate actions column pointing at a write endpoint that doesn't
    # exist on the backend (tests/api/test_customers.py proves that side).
    text = CUSTOMERS_TABLE.read_text(encoding="utf-8")
    for forbidden in ("createMasterData", "updateMasterData", "onSubmit", "Dialog"):
        assert forbidden not in text, f"customers table unexpectedly references {forbidden!r}"
