import { test, expect } from "@playwright/test";

// Unit 9/U19: hard permission boundary (proven at the DB layer by
// backend/tests/infra/test_sandbox_boundary.py) plus the soft boundary —
// a confirm dialog gating any write statement. This exercises both through
// the real UI against the real sandbox-role connection, not just the API.
test("running the default read query against seeded product data returns real rows", async ({
  page,
}) => {
  await page.goto("/query");

  // Default statement in the editor is "select * from product limit 50;"
  await page.getByRole("button", { name: "Run" }).click();

  // A longer timeout than the 5s default: this is the sandbox role's very
  // first query since the backend just booted (fresh connection pool, cold
  // query plan), and on GitHub's shared 2-core runners that round trip
  // consistently took longer than 5s in practice (observed: failed twice,
  // including after Playwright's own automatic retry, on a run where the
  // other 12 specs all passed comfortably within the default).
  await expect(page.getByText(/\d+ row\(s\)/)).toBeVisible({ timeout: 15_000 });
  await expect(page.locator("table thead th")).toContainText(["sku"]);
});

test("submitting a write statement is gated behind a confirmation dialog", async ({ page }) => {
  await page.goto("/query");

  const editor = page.locator(".cm-content");
  await editor.click();
  await editor.press("ControlOrMeta+a");
  await editor.pressSequentially("update product set sku = sku;");

  await page.getByRole("button", { name: "Run" }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Confirm before running")).toBeVisible();
  // Scoped to the dialog — query history (persisted across runs against the
  // shared dev DB) can independently contain its own "write" badge from an
  // earlier run, which would otherwise make this a strict-mode ambiguity.
  await expect(dialog.getByText("write")).toBeVisible();

  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).not.toBeVisible();
});
