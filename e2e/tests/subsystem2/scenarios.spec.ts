import { test, expect } from "@playwright/test";

// Unit 18: Builder-side scenario controls. The bootstrap seeds (baseline
// master data, users, world-state/clock) deliberately don't create any
// Scenario rows — those only exist once a real Builder session creates one
// (U22+) — so a fresh environment's true state is the empty-state message,
// not an empty table silently rendered as if nothing were wrong.
//
// Filtered to `status=cancelled`, not the unfiltered list: Unit 34 added
// fixture-seeding specs (evaluation.spec.ts, orbynadmin-analyst/
// reflection.spec.ts) that share this same running backend/database and
// each create a real (draft -> approved -> active) scenario of their own
// — this project's own E2E design deliberately runs against real
// processes with no network-layer stubbing (playwright.config.ts's own
// comment: "no meaningful way to stub that ... without testing nothing"),
// so an unfiltered "the whole list is empty" assertion is incompatible
// with any other spec ever creating a scenario, regardless of run order
// (fullyParallel doesn't guarantee this file runs first). Nothing in this
// suite ever cancels a scenario, so `cancelled` stays genuinely,
// deterministically empty while still exercising the exact same
// EmptyState render path this test was written to catch.
test("scenarios page renders its real empty state for a status with no scenarios, not an error", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });

  await page.goto("/scenarios?status=cancelled");

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
