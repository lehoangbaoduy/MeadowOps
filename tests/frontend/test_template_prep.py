"""Unit 7 (MEADOWOPS-INFRA-002): frontend template prep. Structural checks
only — no rendering, no build. Verifies the repo *layout* facts Appendix D
specifies, independent of any particular file's content, so this test is
red before the unit starts and green only once the unit is actually done:
it doesn't encode a curated list of fabricated strings that happens to
match what was found by hand (see DD discussion in the progress doc).

Run explicitly, not swept into the backend suite (backend/pyproject.toml's
testpaths is scoped to backend/tests):
    backend/.venv/bin/pytest tests/frontend/ -q
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SUBSYSTEM_1 = REPO_ROOT / "templates/subsystem_1/orbynadmin"
SUBSYSTEM_2 = REPO_ROOT / "templates/subsystem_2/shadcn-dashboard"
S2_APP = SUBSYSTEM_2 / "nextjs-version"

S1_KEEP = [
    "src/app/(app)/activity",
    "src/app/(app)/customers",
    "src/app/(app)/dashboard",
    "src/app/(app)/dashboard/analytics",
    "src/app/(app)/dashboard/logistics",
    "src/app/(app)/inventory",
    "src/app/(app)/notifications",
    "src/app/(app)/orders",
    "src/app/(app)/reports",
    "src/app/(app)/settings",
    "src/app/(app)/shipping",
    "src/app/(auth)/login",
    "src/app/errors/404",
]

S1_DISCARD = [
    "src/app/(app)/apps",
    "src/app/(app)/blog",
    "src/app/(app)/cart",
    "src/app/(app)/categories",
    "src/app/(app)/checkout",
    "src/app/(app)/contacts",
    "src/app/(app)/developers",
    "src/app/(app)/discounts",
    "src/app/(app)/examples",
    "src/app/(app)/help",
    "src/app/(app)/integrations",
    "src/app/(app)/invoices",
    "src/app/(app)/pricing",
    "src/app/(app)/products",
    "src/app/(app)/profile",
    "src/app/(app)/projects",
    "src/app/(app)/reviews",
    "src/app/(app)/roles",
    "src/app/(app)/search",
    "src/app/(app)/storefront",
    "src/app/(app)/support",
    "src/app/(app)/team",
    "src/app/(app)/dashboard/crm",
    "src/app/(app)/dashboard/crypto",
    "src/app/(app)/dashboard/ecommerce",
    "src/app/(app)/dashboard/healthcare",
    "src/app/(app)/dashboard/hr",
    "src/app/(app)/dashboard/real-estate",
    "src/app/(auth)/forgot-password",
    "src/app/(auth)/lock",
    "src/app/(auth)/register",
    "src/app/(auth)/reset-password",
    "src/app/(auth)/verify-otp",
    "src/app/errors/403",
    "src/app/errors/500",
    "src/app/errors/503",
    "src/app/coming-soon",
    "src/app/landing",
    "src/app/maintenance",
    "src/app/onboarding",
    "src/data/index.ts",
    "src/app/(app)/support/tickets-data.ts",
]

S2_KEEP = [
    "src/app/(auth)/sign-in",
    "src/app/(auth)/errors/not-found",
    "src/app/(dashboard)/calendar",
    "src/app/(dashboard)/dashboard",
    "src/app/(dashboard)/mail",
    "src/app/(dashboard)/settings",
    "src/app/(dashboard)/settings/account",
    "src/app/(dashboard)/settings/appearance",
    "src/app/(dashboard)/settings/notifications",
    "src/app/(dashboard)/settings/user",
    "src/app/(dashboard)/tasks",
    "src/app/(dashboard)/users",
]

S2_DISCARD = [
    "src/app/(auth)/errors/forbidden",
    "src/app/(auth)/errors/internal-server-error",
    "src/app/(auth)/errors/unauthorized",
    "src/app/(auth)/errors/under-maintenance",
    "src/app/(auth)/forgot-password",
    "src/app/(auth)/forgot-password-2",
    "src/app/(auth)/forgot-password-3",
    "src/app/(auth)/sign-in-2",
    "src/app/(auth)/sign-in-3",
    "src/app/(auth)/sign-up",
    "src/app/(auth)/sign-up-2",
    "src/app/(auth)/sign-up-3",
    "src/app/(dashboard)/chat",
    "src/app/(dashboard)/dashboard-2",
    "src/app/(dashboard)/faqs",
    "src/app/(dashboard)/pricing",
    "src/app/(dashboard)/production",
    "src/app/(dashboard)/settings/billing",
    "src/app/(dashboard)/settings/connections",
    "src/app/landing",
]


def test_vite_version_sibling_is_deleted() -> None:
    assert not (SUBSYSTEM_2 / "vite-version").exists()


def test_neither_template_has_a_nested_git_directory() -> None:
    assert not (SUBSYSTEM_1 / ".git").exists()
    assert not (S2_APP / ".git").exists()
    assert not (SUBSYSTEM_2 / ".git").exists()


def test_subsystem_1_keep_list_present() -> None:
    missing = [p for p in S1_KEEP if not (SUBSYSTEM_1 / p).exists()]
    assert not missing, f"Appendix D.1 pages missing: {missing}"


def test_subsystem_1_discard_list_absent() -> None:
    present = [p for p in S1_DISCARD if (SUBSYSTEM_1 / p).exists()]
    assert not present, f"Appendix D.1 out-of-scope paths still present: {present}"


def test_subsystem_2_keep_list_present() -> None:
    missing = [p for p in S2_KEEP if not (S2_APP / p).exists()]
    assert not missing, f"Appendix D.2 pages missing: {missing}"


def test_subsystem_2_discard_list_absent() -> None:
    present = [p for p in S2_DISCARD if (S2_APP / p).exists()]
    assert not present, f"Appendix D.2 out-of-scope paths still present: {present}"


def test_subsystem_1_nothing_imports_the_deleted_demo_data_module() -> None:
    hits = [
        str(f)
        for f in (SUBSYSTEM_1 / "src").rglob("*.ts*")
        if '"@/data"' in f.read_text(encoding="utf-8")
    ]
    assert not hits, f"still importing the deleted demo-data module: {hits}"


def test_no_dicebear_placeholder_avatars_remain() -> None:
    """api.dicebear.com is the single most consistent fabricated-data marker
    across both templates (fake customers, drivers, teammates, orders) —
    a genuinely stripped template has none of it anywhere in src/."""
    hits = []
    for base in (SUBSYSTEM_1, S2_APP):
        for f in (base / "src").rglob("*.ts*"):
            if "api.dicebear.com" in f.read_text(encoding="utf-8"):
                hits.append(str(f))
    assert not hits, f"fabricated dicebear avatar URLs remain: {hits}"
