"""Unit 24 (MEADOWOPS-DOM-018, PRD Appendix D.1): orbynadmin's Activity page
wired to the real Decision & Event Ledger API, replacing Unit 21's
EmptyState-only placeholder ("Ledger entries appear here once this view is
wired to the real API layer.").

Structural checks only, same style as test_dashboard_skeleton.py/
test_customers_page.py - no rendering, no build (npm run build is this
unit's actual correctness gate, run separately - DD-17, no JS unit test
runner in this repo).

Unit 34 amends the original Unit 24 read-only scope: PRD 6.6 step 10's
decision recording now has a real caller (Unit 25's evaluation pipeline,
via a Builder acting on its output), so the write actions this test
previously asserted were absent (propose/accept/reject/resubmit/implement/
partially-implement/outcome) now have a real UI entry point -
DecisionActions/ProposeDecisionDialog, gated the same way every other
write route in this app is: the backend's own require_admin
(app.api.ledger), not client-side role detection (no such mechanism exists
anywhere else in this app - see thread-view.tsx's own docstring).
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SUBSYSTEM_1 = REPO_ROOT / "frontend/subsystem_1/orbynadmin"
ACTIVITY_PAGE = SUBSYSTEM_1 / "src/app/(app)/activity/page.tsx"
DECISIONS_TABLE = SUBSYSTEM_1 / "src/components/decisions-table.tsx"
DECISION_ACTIONS = SUBSYSTEM_1 / "src/components/decision-actions.tsx"
PROPOSE_DECISION_DIALOG = SUBSYSTEM_1 / "src/components/propose-decision-dialog.tsx"
LEDGER_API = SUBSYSTEM_1 / "src/lib/ledger-api.ts"
LEDGER_TYPES = SUBSYSTEM_1 / "src/types/ledger.ts"


def test_decisions_table_component_exists() -> None:
    assert DECISIONS_TABLE.is_file()


def test_decision_actions_component_exists() -> None:
    assert DECISION_ACTIONS.is_file()


def test_propose_decision_dialog_component_exists() -> None:
    assert PROPOSE_DECISION_DIALOG.is_file()


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


def test_activity_page_can_propose_a_decision() -> None:
    text = ACTIVITY_PAGE.read_text(encoding="utf-8")
    assert "ProposeDecisionDialog" in text


def test_decisions_table_renders_row_actions() -> None:
    text = DECISIONS_TABLE.read_text(encoding="utf-8")
    assert "DecisionActions" in text


def test_decision_actions_drives_every_transition_route() -> None:
    # Each of app.api.ledger's require_admin transition routes must have a
    # real UI caller, not just a backend endpoint nothing reaches - same
    # discipline tests/architecture/test_subsystem_boundary.py's own
    # route-inventory allowlist enforces at the backend layer.
    text = DECISION_ACTIONS.read_text(encoding="utf-8")
    for expected in (
        "request-clarification",
        "resubmit",
        "reject",
        "implement",
        "partially-implement",
        "/accept",
        "/outcome",
    ):
        assert expected in text, f"decision-actions.tsx is missing a caller for {expected!r}"
