import { test, expect } from "@playwright/test";

import "../../env";

// Unauthenticated flow — overrides the project's default (already-logged-in)
// storageState with an empty one, since Unit 17a's login is the one thing
// every other orbynadmin spec deliberately skips by starting pre-authed.
test.use({ storageState: { cookies: [], origins: [] } });

test("unauthenticated visit to a protected page is sent to /login", async ({ page }) => {
  await page.goto("/customers");
  await expect(page).toHaveURL(/\/login/);
});

test("signing in with valid admin credentials via the real form reaches the dashboard", async ({
  page,
}) => {
  const email = process.env.MEADOWOPS_INITIAL_ADMIN_EMAIL;
  const password = process.env.MEADOWOPS_INITIAL_ADMIN_PASSWORD;
  if (!email || !password) {
    throw new Error("MEADOWOPS_INITIAL_ADMIN_EMAIL/PASSWORD not set in this worker's env");
  }

  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL(/\/dashboard/);
});

test("signing in with a wrong password shows an error and stays on /login", async ({ page }) => {
  const email = process.env.MEADOWOPS_INITIAL_ADMIN_EMAIL;
  if (!email) {
    throw new Error("MEADOWOPS_INITIAL_ADMIN_EMAIL not set in this worker's env");
  }

  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("definitely-not-the-real-password");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByText("Invalid credentials")).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
});
