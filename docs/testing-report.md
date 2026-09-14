# Testing Report

PRD §1.6 / Phase 4 exit criteria: "a testing report summarizing coverage
and results." Counts below are regenerable, not narrated from memory —
see the exact command next to each. Snapshot taken 2026-09-13, current
branch `master`.

## Suite inventory

| Suite | Count | Command | Runs in CI? |
|---|---|---|---|
| Backend unit/integration/architecture (`backend/tests/`) | 1288 | `cd backend && uv run --frozen pytest -q` | Yes — `.github/workflows/backend-ci.yml` |
| Repo-root frontend structural checks (`tests/frontend/`) | 23 | `cd backend && uv run --frozen pytest ../tests/frontend -q` | Yes — `backend-ci.yml`, "Run repo-root frontend structural checks" step |
| Playwright E2E (`e2e/tests/`) | 13 | `cd e2e && npx playwright test` | Yes — `.github/workflows/e2e.yml`, its own job |
| orbynadmin/subsystem_2 production build | — | `npm run build` in each app | Indirectly — `e2e.yml`'s `webServer` entries run `npm run build && npm run start` before any spec executes, so a broken build fails the E2E job even though "build" isn't a named step |
| orbynadmin/subsystem_2 ESLint | — | `npm run lint` in each app | **No.** Runs only via `scripts/ci.sh`, locally, non-blocking (see gap below) |

Both CI workflows were last independently confirmed green via the GitHub
Actions REST API on the current `master` HEAD (see
prd/MeadowOps_progress.md's U31 entry for the specific run IDs and the
fixes that got them there — two rounds of real CI-only failures: a
Starlette `TestClient.websocket_connect()` race under CI's slower
scheduler, and the E2E suite's Query Playground test running before the
`sandbox` schema had ever been refreshed on a genuinely fresh database).

## Known coverage gap: lint has no CI enforcement

`scripts/ci.sh` runs `npm run lint` for both frontends, but treats it as
non-blocking (`|| echo ... non-blocking`) for two pre-existing, out-of-scope
reasons documented in that script's own header — orbynadmin has ~5
findings in vendored template files (Unit 8), and subsystem_2's ESLint
config has a pre-existing `eslint-config-next`/`@eslint/eslintrc`
compatibility bug unrelated to any unit's own changes. Neither
`backend-ci.yml` nor `e2e.yml` invokes lint at all, blocking or not — so a
newly introduced lint violation in either frontend can merge to `master`
with both GitHub Actions workflows green. This is a real, currently-open
gap, not a decision to fix as part of this documentation pass; noting it
here rather than letting the "all CI green" fact imply full coverage it
doesn't have.

## Metadata gap found while writing docs/data-dictionary.md — fixed 2026-09-14

`backend/app/db/__init__.py` never imported `app.db.evaluation`,
`app.db.human_review`, or `app.db.portfolio` — so `Base.metadata` (what
`alembic revision --autogenerate` diffs against, per `alembic/env.py`) was
silently missing all three `engine`-schema tables that migrations
0020/0021 actually created. A future autogenerate run would have proposed
`DROP TABLE` for all three. Fixed by adding the three imports (the user
applied the edit directly, since `backend/` sits behind a harness-init gate
this documentation pass didn't have standing to clear itself). Verified
two ways after the fix: `alembic revision --autogenerate` against the real
dev database no longer proposes dropping any of the three tables (the
throwaway revision it generated was inspected, confirmed clean of them,
and deleted without being applied — the only remaining proposed drops are
pre-existing, unrelated drift: the `sandbox` schema's tables, which are
runtime-created by `app/services/sandbox_refresh.py` and were never
migration-managed, and a handful of partial/functional indexes declared
via raw `op.execute()` rather than a SQLAlchemy `Index` object); the full
backend suite still passes 1288/1288 with the fix in place. No regression
test was added to catch a future recurrence of the same gap (e.g. a new
model module added without a corresponding import) — a real residual risk,
left open rather than silently addressed.

## Edge-case catalog (PRD 9.2)

32/32 rows closed as of 2026-09-13 (Phase 3 exit criterion; see
prd/MeadowOps_progress.md §8 for the full per-row table and B1/B2 for the
two that closed it: managed-Postgres deployment target and a live
backup/restore drill against real data, not a simulated one).

## What "1288 backend tests" actually covers

Not an undifferentiated pile — the suite is organized by what it protects:

- **Domain/service unit tests** — business logic in isolation (scheduler
  ticks, exception rules, KPI computation, scenario state machine,
  persona-chat redaction, evaluation scoring).
- **API tests** — every route, both roles (Admin/Analyst), including the
  negative case (Analyst denied at every Builder-only route).
- **Integration tests** — real Postgres round trips (not mocked), the
  genuine `httpx.ASGITransport` Subsystem 1↔2 boundary test, WebSocket chat
  delivery.
- **Infra tests** — the sandbox permission boundary proven at the database
  layer (`tests/infra/test_sandbox_boundary.py`), migration idempotency.
- **Architecture tests** — the AST-based import-boundary checker
  (`tests/architecture/test_subsystem_boundary.py`) and a route-inventory
  allowlist test, both of which fail the build on a structural regression
  rather than a behavioral one.

## What the E2E suite covers that the backend suite structurally cannot

The 13 Playwright specs are deliberately not a re-test of backend logic —
they exercise the real browser against real seeded/QA data through both
frontends' actual UI, catching classes of bug no `TestClient` call can:
login redirects, the Query Playground's write-statement confirmation
dialog, role-gating at the page level (not just the route level), and the
`sandbox` schema's lazy-population behavior (the exact bug this suite's own
`global-setup.ts` was written to catch — see its comments).

## Out of scope for this report

Frontend unit tests (component-level, non-E2E) do not exist for either
frontend — this project's test strategy relies on the backend suite plus
the Playwright suite for frontend correctness, not a third unit-test layer;
no unit ever scoped one. Load/performance testing was never scoped (PRD
has no NFR requiring it for Build & Test). Both are legitimate future gaps,
not silently-dropped requirements — neither appears in PRD §1.6/§5.8/Phase
4 exit criteria as something Done requires.
