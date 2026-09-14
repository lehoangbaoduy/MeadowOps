import { test, expect } from "@playwright/test";

// Unit 34: the Decision & Event Ledger's write actions (propose through
// outcome), added to orbynadmin's Activity page after Unit 24 deliberately
// shipped it read-only. Ledger data isn't scenario-scoped or per-test
// isolated (a genuinely global log, same as the real app) — this spec
// walks one decision through its entire lifecycle in a single test, using
// a title unique per run so parallel workers/re-runs never collide with
// each other's rows.
const TITLE = `E2E ledger decision ${Date.now()}`;

test("a decision can be proposed and walked through its full lifecycle from the Activity page", async ({
  page,
}) => {
  await page.goto("/activity");

  await page.getByRole("button", { name: "Propose Decision" }).click();
  const proposeDialog = page.getByRole("dialog", { name: "Propose a decision" });
  await expect(proposeDialog).toBeVisible();
  await proposeDialog.getByRole("combobox").click();
  await page.getByRole("option", { name: "Supplier" }).click();
  await proposeDialog.getByLabel("Entity ID").fill("S-004");
  await proposeDialog.getByLabel("Title").fill(TITLE);
  await proposeDialog.getByLabel("Summary").fill("E2E: raised via the Propose Decision dialog.");
  await proposeDialog.getByRole("button", { name: "Propose" }).click();
  await expect(proposeDialog).toBeHidden();

  const row = page.getByRole("row", { name: new RegExp(TITLE) });
  await expect(row).toBeVisible();
  await expect(row.getByText("Proposed")).toBeVisible();

  await row.getByRole("button", { name: "Accept" }).click();
  const acceptDialog = page.getByRole("dialog", { name: "Accept decision" });
  await expect(acceptDialog).toBeVisible();
  await acceptDialog.getByRole("button", { name: "Accept" }).click();
  await expect(acceptDialog).toBeHidden();
  await expect(row.getByText("Accepted")).toBeVisible();

  await row.getByRole("button", { name: "Mark Implemented" }).click();
  await expect(row.getByText("Implemented", { exact: true })).toBeVisible();

  await row.getByRole("button", { name: "Record Outcome" }).click();
  const outcomeDialog = page.getByRole("dialog", { name: "Record outcome" });
  await expect(outcomeDialog).toBeVisible();
  await outcomeDialog.getByRole("combobox").click();
  await page.getByRole("option", { name: "Succeeded", exact: true }).click();
  await outcomeDialog.getByLabel("Notes (optional)").fill("E2E: closing the loop.");
  await outcomeDialog.getByRole("button", { name: "Save outcome" }).click();
  await expect(outcomeDialog).toBeHidden();

  await expect(row.getByText("Outcome Observed")).toBeVisible();
  await expect(row.getByText("succeeded")).toBeVisible();
});

test("a rejected decision shows no further actions", async ({ page }) => {
  const rejectTitle = `E2E reject ${Date.now()}`;

  await page.goto("/activity");
  await page.getByRole("button", { name: "Propose Decision" }).click();
  const proposeDialog = page.getByRole("dialog", { name: "Propose a decision" });
  await proposeDialog.getByRole("combobox").click();
  await page.getByRole("option", { name: "Warehouse" }).click();
  await proposeDialog.getByLabel("Entity ID").fill("WH-001");
  await proposeDialog.getByLabel("Title").fill(rejectTitle);
  await proposeDialog.getByLabel("Summary").fill("E2E: to be rejected.");
  await proposeDialog.getByRole("button", { name: "Propose" }).click();
  await expect(proposeDialog).toBeHidden();

  const row = page.getByRole("row", { name: new RegExp(rejectTitle) });
  await expect(row.getByText("Proposed")).toBeVisible();

  page.once("dialog", (dialog) => dialog.accept());
  await row.getByRole("button", { name: "Reject" }).click();

  await expect(row.getByText("Rejected")).toBeVisible();
  await expect(row.getByRole("button")).toHaveCount(0);
});
