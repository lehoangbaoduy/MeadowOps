import { test, expect } from "@playwright/test";

import "../../env";

// Unit 20a: subsystem_2 is admin-only by design and fails closed on any
// other role at the /api/login route itself (checked before the session
// cookie is ever set — see that route's own docstring), unlike orbynadmin
// which accepts both roles. This is the one property that makes the two
// apps' auth genuinely different, so it gets its own unauthenticated spec
// rather than reusing the default (already-admin-authed) storageState.
test.use({ storageState: { cookies: [], origins: [] } });

test("an analyst account is rejected at sign-in, even though the password is correct", async ({
  page,
}) => {
  const email = process.env.MEADOWOPS_INITIAL_ANALYST_EMAIL;
  const password = process.env.MEADOWOPS_INITIAL_ANALYST_PASSWORD;
  if (!email || !password) {
    throw new Error("MEADOWOPS_INITIAL_ANALYST_EMAIL/PASSWORD not set in this worker's env");
  }

  await page.goto("/sign-in");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(
    page.getByText("This workspace is available to Builder (admin) accounts only")
  ).toBeVisible();
  await expect(page).toHaveURL(/\/sign-in/);
});

test("an admin account signs in and reaches the dashboard", async ({ page }) => {
  const email = process.env.MEADOWOPS_INITIAL_ADMIN_EMAIL;
  const password = process.env.MEADOWOPS_INITIAL_ADMIN_PASSWORD;
  if (!email || !password) {
    throw new Error("MEADOWOPS_INITIAL_ADMIN_EMAIL/PASSWORD not set in this worker's env");
  }

  await page.goto("/sign-in");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL(/\/dashboard/);
});
