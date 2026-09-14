import { execFileSync } from "node:child_process";
import path from "node:path";

import { test, expect } from "@playwright/test";

// Unit 34: the Analyst's portfolio reflection form, which replaces
// ThreadView's composer once a thread is completed. Seeded via the same
// scripts/seed-evaluation-fixture.sh as tests/subsystem2/evaluation.spec.ts
// (see that file's own header for why a real evaluation can't be produced
// through the running app right now) - `--persona cfo` here specifically
// so this thread is selectable by persona label alone in orbynadmin's
// thread-list.tsx, which exposes no other stable per-thread selector, and
// doesn't collide with the `operations_director` fixture that spec seeds.
//
// describe.serial: the second test depends on the first test's submitted
// reflection to exercise the 409-as-"already submitted" path for real,
// same reasoning as evaluation.spec.ts's own describe.serial.
test.describe.serial("orbynadmin Chat: Analyst portfolio reflection", () => {
  test.beforeAll(() => {
    const scriptPath = path.resolve(__dirname, "../../scripts/seed-evaluation-fixture.sh");
    execFileSync("bash", [scriptPath, "--persona", "cfo"], { encoding: "utf-8" });
  });

  test("the composer is replaced by the reflection form on a completed thread, and submitting it works", async ({
    page,
  }) => {
    await page.goto("/chat");

    await page.getByRole("button", { name: /CFO/ }).last().click();
    await expect(page.getByRole("heading", { name: "This scenario is complete" })).toBeVisible();
    await expect(page.getByPlaceholder(/Reply as the Analyst/)).toHaveCount(0);

    await page.getByLabel("What happened in this scenario?").fill("E2E: walked the East low-stock case with the CFO.");
    await page
      .getByLabel("What did you initially think was going on?")
      .fill("E2E: assumed a shipment delay at first.");
    await page.getByLabel("What evidence mattered most?").fill("E2E: the fill-rate trend and stockout frequency.");
    await page.getByLabel("What did you miss, if anything?").fill("E2E: hadn't checked reporting lag yet.");
    await page
      .getByLabel("What changed in your thinking after pushback?")
      .fill("E2E: confirmed the warehouse's on-time claim before concluding.");
    await page
      .getByLabel("What would you do differently next time?")
      .fill("E2E: check the second data source earlier.");
    await page.getByLabel("What skill did this improve?").fill("E2E: cross-checking stakeholder claims.");

    await page.getByRole("button", { name: "Submit reflection" }).click();
    await expect(
      page.getByText("This scenario is complete. Your reflection has been recorded — thank you.")
    ).toBeVisible();
  });

  test("re-selecting the same completed thread and submitting again is handled as already recorded", async ({
    page,
  }) => {
    await page.goto("/chat");
    await page.getByRole("button", { name: /CFO/ }).last().click();

    await expect(page.getByRole("heading", { name: "This scenario is complete" })).toBeVisible();
    for (const label of [
      "What happened in this scenario?",
      "What did you initially think was going on?",
      "What evidence mattered most?",
      "What did you miss, if anything?",
      "What changed in your thinking after pushback?",
      "What would you do differently next time?",
      "What skill did this improve?",
    ]) {
      await page.getByLabel(label).fill("E2E: second attempt, expect 409-as-already-submitted.");
    }
    await page.getByRole("button", { name: "Submit reflection" }).click();

    await expect(
      page.getByText("This scenario is complete. Your reflection has been recorded — thank you.")
    ).toBeVisible();
  });
});
