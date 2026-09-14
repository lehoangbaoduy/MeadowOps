"""Unit 12b (MEADOWOPS-UI-002): control-tower dashboard skeleton — real
KPI-card grid layout at orbynadmin's /dashboard/logistics (PRD Appendix D:
"Logistics dashboard -> Executive/Overview KPI view ... OTIF/fill
rate/days-of-supply cards"), replacing Unit 7's EmptyState placeholder.

Structural checks only, same style as Unit 7's test_template_prep.py — no
rendering, no build. This unit deliberately doesn't wire real numbers (the
KPI engine is Unit 14/16, not yet built), so the second test below guards
against the specific mistake that would defeat the point of a "skeleton":
a hardcoded-looking demo percentage slipping in instead of the real
placeholder dash.

EXPECTED_KPI_LABELS originally listed all five PRD Appendix A KPIs
(including "Days of Supply"), written before Unit 14 existed. Unit 14 later
made — and had security-reviewed and approved — the deliberate call that
days_of_supply is *not* a single global scalar the way the other four are:
it's per product/warehouse (see app/db/kpi.py's KpiSnapshot/
DaysOfSupplySnapshot docstrings). PRD S1-FR-3's "calculate and display" is
satisfied for it via the Inventory view's own table and drill-down
(inventory-table.tsx, reports/[id]/page.tsx) instead of an Executive-page
card. Unit 31 found this test's expectation was stale against that later,
reviewed design (caught by wiring this file into real CI for the first
time — it had never run anywhere but a local, non-automated `scripts/
ci.sh` before) and corrected it here rather than force-adding a fabricated
network-wide average onto the Executive page to make the old assertion
pass.

Run explicitly, not swept into the backend suite:
    backend/.venv/bin/pytest tests/frontend/ -q
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SUBSYSTEM_1 = REPO_ROOT / "frontend/subsystem_1/orbynadmin"
LOGISTICS_PAGE = SUBSYSTEM_1 / "src/app/(app)/dashboard/logistics/page.tsx"
KPI_CARD_COMPONENT = SUBSYSTEM_1 / "src/components/kpi-card.tsx"

# PRD Appendix A's four global-scalar starter KPIs, same order as Unit 10's
# backend/sql/kpi/ files. Days of supply is excluded on purpose — see the
# module docstring.
EXPECTED_KPI_LABELS = [
    "OTIF",
    "Fill Rate",
    "Order Cycle Time",
    "Perfect Order Rate",
]

# A bare number followed by a percent sign or "days" is the shape a
# hardcoded demo figure would take in prose/JSX text (e.g. "94.2%" or
# "3.5 days") — deliberately requires the suffix, not just a bare digit
# sequence, since Tailwind classNames throughout this file (gap-2, size-4,
# ml-1, text-2xl) are exactly that shape and would otherwise false-positive.
# Case-insensitive: "3.5 Days" (capitalized, as it could plausibly appear
# near "Days of Supply") wouldn't match the all-lowercase version this test
# originally shipped with. Comments are stripped first: this unit's own
# explanatory prose ("Deliberately not ... '0 days'") legitimately discusses
# the pattern without being an instance of it — caught by this test against
# its own first draft, not a hypothetical.
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"//.*")
_DEMO_LOOKING_NUMBER = re.compile(r"\b\d+(\.\d+)?\s*(%|days)\b", re.IGNORECASE)
# The value span specifically catches the shape a %/days-suffixed regex
# can't: KpiCard renders its value and unit in separate sibling <span>s, so
# a regressed bare value (e.g. "94" with no adjacent suffix) needs its own
# check, scoped to exactly that span rather than a file-wide "—" substring
# check (security review of this unit: the file-wide version would stay
# green even if this span's own content changed, as long as an em dash
# still appeared anywhere else in the file — e.g. in a doc comment).
_VALUE_SPAN = re.compile(r'<span aria-hidden="true">(.*?)</span>')


def _strip_comments(text: str) -> str:
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))


def test_kpi_card_component_exists() -> None:
    assert KPI_CARD_COMPONENT.is_file()


def test_logistics_page_no_longer_uses_the_empty_state_placeholder() -> None:
    text = LOGISTICS_PAGE.read_text(encoding="utf-8")
    assert "EmptyState" not in text


def test_logistics_page_renders_all_four_global_scalar_kpi_card_slots() -> None:
    text = LOGISTICS_PAGE.read_text(encoding="utf-8")
    missing = [label for label in EXPECTED_KPI_LABELS if label not in text]
    assert not missing, f"KPI card slots missing from the logistics page: {missing}"


def test_logistics_page_has_no_hardcoded_looking_demo_figures() -> None:
    text = _strip_comments(LOGISTICS_PAGE.read_text(encoding="utf-8"))
    hits = _DEMO_LOOKING_NUMBER.findall(text)
    assert not hits, f"logistics page contains what looks like a hardcoded KPI value: {hits}"


def test_kpi_card_value_span_is_the_placeholder_not_a_fabricated_value() -> None:
    text = _strip_comments(KPI_CARD_COMPONENT.read_text(encoding="utf-8"))
    match = _VALUE_SPAN.search(text)
    assert match is not None, "KpiCard's aria-hidden value span not found"
    assert match.group(1) == "—", f"value span content is not the placeholder: {match.group(1)!r}"
