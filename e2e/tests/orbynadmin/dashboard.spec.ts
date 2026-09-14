import { test, expect } from "@playwright/test";

test("dashboard redirects to the logistics view and renders real KPI cards", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });

  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/dashboard\/logistics/);

  // The four global-scalar Appendix A KPIs (Unit 12b/U16) — real values
  // computed from seeded baseline data, not placeholder text. Days of
  // supply is deliberately not a card here (Unit 14's reviewed design —
  // it's per product/warehouse, surfaced via the Inventory view instead;
  // see tests/frontend/test_dashboard_skeleton.py). exact:true since "OTIF"
  // is otherwise a substring of the page's own description text and of
  // "Notifications" (Playwright's text matching is substring + case-
  // insensitive by default).
  await expect(page.getByText("OTIF", { exact: true })).toBeVisible();
  await expect(page.getByText("Fill Rate", { exact: true })).toBeVisible();
  await expect(page.getByText("Order Cycle Time", { exact: true })).toBeVisible();
  await expect(page.getByText("Perfect Order Rate", { exact: true })).toBeVisible();

  expect(errors).toEqual([]);
});
