import { request } from "@playwright/test";
import { config as loadEnv } from "dotenv";
import fs from "node:fs";
import path from "node:path";

// Logs in once per (app, role) pair by POSTing each app's own `/api/login`
// route handler directly (not by clicking through the form) and saves the
// resulting httpOnly session cookie via `storageState`, so individual specs
// start already authenticated. Two apps, not a uniform two roles each:
// orbynadmin accepts both admin and analyst (Unit 17a); subsystem_2 is
// admin-only by design and fails closed on any other role at the route
// level (Unit 20a's `/api/login` docstring) - so there is deliberately no
// subsystem2-analyst state to create.
const AUTH_DIR = path.resolve(__dirname, ".auth");

async function login(
  baseURL: string,
  email: string,
  password: string,
  afterLogin?: (context: Awaited<ReturnType<typeof request.newContext>>) => Promise<void>
): Promise<Buffer> {
  const context = await request.newContext({ baseURL });
  const response = await context.post("/api/login", { data: { email, password } });
  if (!response.ok()) {
    throw new Error(
      `global-setup: login against ${baseURL}/api/login failed with ${response.status()}`
    );
  }
  if (afterLogin) {
    await afterLogin(context);
  }
  const state = await context.storageState();
  await context.dispose();
  return Buffer.from(JSON.stringify(state));
}

// Unit 9/19's meadowops_sandbox role only ever queries the `sandbox` schema
// - which sandbox_refresh.py's own docstring confirms is built fresh by a
// staging-schema-then-atomic-rename swap, not something migrations
// pre-populate. On a genuinely fresh database (CI's own ephemeral Postgres;
// never an issue on this project's long-lived local dev DB, which some
// earlier unit's manual verification already refreshed) the `sandbox`
// schema has no tables at all until this runs once - found by a real
// GitHub Actions failure (query-playground.spec.ts's default `select *
// from product` erroring with "relation does not exist", not a timeout as
// first assumed) rather than reasoned out in advance.
async function refreshSandbox(context: Awaited<ReturnType<typeof request.newContext>>): Promise<void> {
  const response = await context.post("/api/query/refresh-sandbox");
  if (!response.ok()) {
    throw new Error(`global-setup: refresh-sandbox failed with ${response.status()}`);
  }
  const body = await response.json();
  if (body.status !== "complete") {
    throw new Error(`global-setup: refresh-sandbox returned status="${body.status}": ${body.error}`);
  }
}

export default async function globalSetup(): Promise<void> {
  loadEnv({ path: path.resolve(__dirname, "../.env") });

  const adminEmail = process.env.MEADOWOPS_INITIAL_ADMIN_EMAIL;
  const adminPassword = process.env.MEADOWOPS_INITIAL_ADMIN_PASSWORD;
  const analystEmail = process.env.MEADOWOPS_INITIAL_ANALYST_EMAIL;
  const analystPassword = process.env.MEADOWOPS_INITIAL_ANALYST_PASSWORD;

  if (!adminEmail || !adminPassword || !analystEmail || !analystPassword) {
    throw new Error(
      "global-setup: MEADOWOPS_INITIAL_{ADMIN,ANALYST}_{EMAIL,PASSWORD} must be set " +
        "(repo-root .env, or the environment in CI) before the E2E suite can log in"
    );
  }

  fs.mkdirSync(AUTH_DIR, { recursive: true });

  const [orbynadminAdmin, orbynadminAnalyst, subsystem2Admin] = await Promise.all([
    login("http://localhost:4001", adminEmail, adminPassword, refreshSandbox),
    login("http://localhost:4001", analystEmail, analystPassword),
    login("http://localhost:4002", adminEmail, adminPassword),
  ]);

  fs.writeFileSync(path.join(AUTH_DIR, "orbynadmin-admin.json"), orbynadminAdmin);
  fs.writeFileSync(path.join(AUTH_DIR, "orbynadmin-analyst.json"), orbynadminAnalyst);
  fs.writeFileSync(path.join(AUTH_DIR, "subsystem2-admin.json"), subsystem2Admin);
}
