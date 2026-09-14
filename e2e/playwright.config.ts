import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

// Unit 31 (MEADOWOPS-HARDEN-002): the first committed browser-level E2E
// suite for either frontend. Every unit before this one verified frontend
// pages via live, interactive Playwright MCP sessions (see e.g. U7, U12c)
// -- real, but not repeatable or CI-checkable. This suite is.
//
// Both frontends are Next.js apps whose pages fetch through their own
// `/api/...` route handlers to the real FastAPI backend, and auth is an
// httpOnly session cookie set by each app's own `/api/login` route (Unit
// 17a / Unit 20a). There is no meaningful way to stub that at the network
// layer without testing nothing, so all three real processes -- backend,
// orbynadmin, subsystem_2 -- are booted for real below via `webServer`,
// against the same local Docker Compose Postgres normal local dev already
// requires (`docker compose up -d` at the repo root).
//
// Login happens once per (app, role) pair in global-setup.ts, which POSTs
// each app's own `/api/login` route and saves the resulting cookie jar via
// `storageState` -- not per-test, and not via clicking through the login
// form every time.
const ROOT_DIR = path.resolve(__dirname, "..");
const AUTH_DIR = path.resolve(__dirname, ".auth");

export default defineConfig({
  testDir: path.resolve(__dirname, "tests"),
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  globalSetup: path.resolve(__dirname, "global-setup.ts"),
  timeout: 30_000,

  use: {
    trace: "on-first-retry",
  },

  projects: [
    {
      name: "orbynadmin-admin",
      testMatch: /orbynadmin\/.*\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        baseURL: "http://localhost:4001",
        storageState: path.join(AUTH_DIR, "orbynadmin-admin.json"),
      },
    },
    {
      name: "orbynadmin-analyst",
      testMatch: /orbynadmin-analyst\/.*\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        baseURL: "http://localhost:4001",
        storageState: path.join(AUTH_DIR, "orbynadmin-analyst.json"),
      },
    },
    {
      name: "subsystem2-admin",
      testMatch: /subsystem2\/.*\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        baseURL: "http://localhost:4002",
        storageState: path.join(AUTH_DIR, "subsystem2-admin.json"),
      },
    },
  ],

  webServer: [
    {
      command: "bash scripts/start-backend.sh",
      cwd: __dirname,
      url: "http://localhost:8000/health",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: "npm run build && npm run start -- -p 4001",
      cwd: path.join(ROOT_DIR, "frontend/subsystem_1/orbynadmin"),
      url: "http://localhost:4001/login",
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
    },
    {
      command: "npm run build && npm run start -- -p 4002",
      cwd: path.join(ROOT_DIR, "frontend/subsystem_2/shadcn-dashboard/nextjs-version"),
      url: "http://localhost:4002/sign-in",
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
    },
  ],
});
