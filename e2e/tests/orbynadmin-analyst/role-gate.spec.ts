import { test, expect } from "@playwright/test";

// Unit 28: the nav entry is hidden from Analyst (cosmetic), but the real
// boundary is the server component's own role check plus the backend's
// require_admin — this proves the boundary itself, not just that a link is
// missing (same "verified, not just asserted" standard as the DB-level
// sandbox boundary in backend/tests/infra/test_sandbox_boundary.py).
test("an analyst navigating directly to the admin query log sees no access, not the data", async ({
  page,
}) => {
  await page.goto("/admin/query-log");
  await expect(page.getByText("You don't have access to this page.")).toBeVisible();
  await expect(page.locator("table")).toHaveCount(0);
});

test("an analyst can still reach their own dashboard and customers pages", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/dashboard\/logistics/);

  await page.goto("/customers");
  await expect(page.locator("table tbody tr").first()).toBeVisible();
});
