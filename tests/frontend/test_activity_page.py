"""Unit 24 (MEADOWOPS-DOM-018, PRD Appendix D.1): orbynadmin's Activity page
wired to the real Decision & Event Ledger API, replacing Unit 21's
EmptyState-only placeholder ("Ledger entries appear here once this view is
wired to the real API layer.").

Structural checks only, same style as test_dashboard_skeleton.py/
test_customers_page.py - no rendering, no build (npm run build is this
unit's actual correctness gate, run separately - DD-17, no JS unit test
runner in this repo).

Read-only, same reasoning as test_customers_page.py's S1-FR-12 exclusion:
this view is a log (PRD Appendix D.1: "Timestamped log pattern fits
directly"), not a place to propose/accept/reject a decision - those write
actions have no UI entry point yet (PRD 6.6 step 10 ties decision recording
to the AI evaluation flow, U25, not built yet), so the table must never
grow a write-shaped action column pointing at an endpoint no caller drives
yet.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SUBSYSTEM_1 = REPO_ROOT / "frontend/subsystem_1/orbynadmin"
ACTIVITY_PAGE = SUBSYSTEM_1 / "src/app/(app)/activity/page.tsx"
DECISIONS_TABLE = SUBSYSTEM_1 / "src/components/decisions-table.tsx"
LEDGER_API = SUBSYSTEM_1 / "src/lib/ledger-api.ts"
LEDGER_TYPES = SUBSYSTEM_1 / "src/types/ledger.ts"


def test_decisions_table_component_exists() -> None:
    assert DECISIONS_TABLE.is_file()


def test_ledger_api_client_exists() -> None:
    assert LEDGER_API.is_file()


def test_ledger_types_exist() -> None:
    assert LEDGER_TYPES.is_file()


def test_activity_page_fetches_from_the_real_ledger_api() -> None:
    text = ACTIVITY_PAGE.read_text(encoding="utf-8")
    assert "listDecisions" in text


def test_activity_page_still_falls_back_to_empty_state_when_the_ledger_is_empty() -> None:
    # Unlike Customers (always-seeded master data), the ledger can
    # genuinely be empty (no decision has ever been proposed) - PRD 9.2's
    # "callback scenario referencing a since-deactivated entity" edge case
    # and this project's own edge-case catalog both require an empty
    # result to render cleanly, not as an error.
    text = ACTIVITY_PAGE.read_text(encoding="utf-8")
    assert "EmptyState" in text


def test_decisions_table_has_no_write_actions() -> None:
    text = DECISIONS_TABLE.read_text(encoding="utf-8")
    for forbidden in ("proposeDecision", "acceptDecision", "rejectDecision", "onSubmit", "Dialog"):
        assert forbidden not in text, f"decisions table unexpectedly references {forbidden!r}"
