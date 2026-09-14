import { execFileSync } from "node:child_process";
import path from "node:path";

import { test, expect } from "@playwright/test";

// Unit 34: the evaluation/human-review/portfolio-export panel on the
// scenario detail page. Needs a scenario with a completed persona thread
// and a real Evaluation row — neither exists in the bootstrap seeds, and
// nothing in the API can create either from a cold start (no route
// creates an ExceptionFlag directly, and app.main.create_app hardcodes
// `app.state.claude_client = None` unconditionally, so POST .../complete
// can never succeed against a running app regardless of whether a real
// ANTHROPIC_API_KEY is configured — see seed_evaluation_fixture.py's own
// docstring). scripts/seed-evaluation-fixture.sh builds one fixture
// (scenario -> approved -> active -> thread -> messages -> evaluation)
// through the real API plus two direct DB inserts, mirroring exactly what
// tests/support/qa_harness.py's own `complete_thread` does (script the
// result rather than depend on a live Claude call).
//
// describe.serial, not the file-level default: fullyParallel in
// playwright.config.ts runs every *test*, not just every file, in its own
// worker by default - two concurrent `beforeAll` calls would both try to
// insert an open ExceptionFlag for the same (category, product,
// warehouse) triple and collide on live.exception_flag's own
// ux_exception_flag_open_entity partial unique index (found via a real
// failed run, not reasoned out in advance). Serial also gives the
// portfolio-export test a real reason to exist as a second test rather
// than a third copy of the same setup: it depends on the human review the
// first test just recorded.
test.describe.serial("scenario detail page: evaluation / human review / portfolio export", () => {
  let scenarioId: string;

  test.beforeAll(() => {
    const scriptPath = path.resolve(__dirname, "../../scripts/seed-evaluation-fixture.sh");
    const output = execFileSync("bash", [scriptPath], { encoding: "utf-8" });
    const lastLine = output.trim().split("\n").pop()!;
    scenarioId = JSON.parse(lastLine).scenario_id;
  });

  test("shows the seeded evaluation, and a human review can be recorded", async ({ page }) => {
    await page.goto(`/scenarios/${scenarioId}`);

    await expect(page.getByRole("heading", { name: "Persona threads" })).toBeVisible();
    await expect(page.getByText("Completed")).toBeVisible();

    // The evaluation itself — already generated (seeded), not the
    // "Complete Thread & Evaluate" empty state.
    await expect(page.getByText("Standard", { exact: true })).toBeVisible();
    await expect(
      page.getByText("Correctly identified the East fill-rate drop and the stockout pattern.")
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Complete Thread & Evaluate" })).toHaveCount(0);

    // No human review yet - the record form, not a read-only display.
    await expect(page.getByRole("heading", { name: "Record human review" })).toBeVisible();
    await page.getByLabel("Reviewer name").fill("E2E Reviewer");
    await page.getByRole("combobox").first().click();
    await page.getByRole("option", { name: "Agree with AI recommendation" }).click();
    await page.getByLabel("Tier assessment notes").fill("E2E: agrees with the seeded recommendation.");
    await page.getByRole("button", { name: "Save human review" }).click();

    await expect(page.getByRole("heading", { name: "Human review" })).toBeVisible();
    await expect(page.getByText("E2E Reviewer — Agreed")).toBeVisible();
  });

  test("the portfolio export dialog shows the transcript, evaluation, and human review", async ({
    page,
  }) => {
    await page.goto(`/scenarios/${scenarioId}`);

    await page.getByRole("button", { name: "View Portfolio Export" }).click();
    const dialog = page.getByRole("dialog", { name: "Portfolio export" });
    await expect(dialog).toBeVisible();

    // Appears twice by design - once as the standalone `trigger` summary,
    // once again as the transcript's own first message (app.domain.
    // portfolio's own `"trigger": messages[0]["body"]` - they're
    // literally the same string, not a coincidence).
    await expect(
      dialog
        .getByText("East's service is getting worse. What's happening and what should we do?")
        .first()
    ).toBeVisible();
    await expect(dialog.getByText(/Fill rate at East has dropped/)).toBeVisible();
    await expect(dialog.getByRole("heading", { name: "Evaluation" })).toBeVisible();
    await expect(dialog.getByRole("heading", { name: "Human review" })).toBeVisible();
    await expect(dialog.getByText(/No reflection submitted yet/)).toBeVisible();
  });

  test("completing an already-completed thread is a no-op state, not a broken one", async ({
    page,
  }) => {
    // Defense against a regression where the panel forgets it already has
    // an evaluation and re-shows the "Complete Thread & Evaluate" button
    // for a thread this fixture already completed.
    await page.goto(`/scenarios/${scenarioId}`);
    await expect(page.getByRole("button", { name: "Complete Thread & Evaluate" })).toHaveCount(0);
  });
});
