import { test, expect } from "@playwright/test";

// Unit 18: Builder-side scenario controls. The bootstrap seeds (baseline
// master data, users, world-state/clock) deliberately don't create any
// Scenario rows — those only exist once a real Builder session creates one
// (U22+) — so a fresh environment's true state is the empty-state message,
// not an empty table silently rendered as if nothing were wrong.
test("scenarios page renders its real empty state on a freshly seeded environment, not an error", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });

  await page.goto("/scenarios");

  await expect(page.getByRole("heading", { name: "Scenarios" })).toBeVisible();
  await expect(page.getByText("No scenarios yet")).toBeVisible();
  expect(errors).toEqual([]);
});

test("status filter links navigate without erroring", async ({ page }) => {
  await page.goto("/scenarios");
  await page.getByRole("link", { name: "Approved" }).click();
  await expect(page).toHaveURL(/status=approved/);
  await expect(page.getByRole("heading", { name: "Scenarios" })).toBeVisible();
});
