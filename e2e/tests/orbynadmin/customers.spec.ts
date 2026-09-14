import { test, expect } from "@playwright/test";

// Unit 12c: the only Appendix D page with non-empty real data available in
// Phase 1 — the baseline generator seeds 9 real customers (see U12c's own
// progress-doc entry). Same live-Postgres-backed behavior U12c originally
// Playwright-verified interactively; this pins it down as a repeatable test.
test("customers page renders seeded real data and its search filter narrows results", async ({
  page,
}) => {
  await page.goto("/customers");

  const rows = page.locator("table tbody tr");
  await expect(rows.first()).toBeVisible();
  const initialCount = await rows.count();
  expect(initialCount).toBeGreaterThan(0);

  await page.getByPlaceholder("Search customers…").fill("zzzz-no-such-customer-zzzz");
  // A filter with no matches still renders one <tr> — DataTable's own "No
  // results." placeholder row (data-table.tsx) — not zero <tr> elements.
  await expect(page.getByText("No results.")).toBeVisible();

  await page.getByPlaceholder("Search customers…").fill("");
  await expect(rows).toHaveCount(initialCount);
});
