# Live Walkthrough Script

PRD §1.6 / Phase 4 exit criteria: "a live walkthrough can be given
end-to-end, using QA/synthetic data, without improvisation." Every route,
button label, and piece of text below was read directly from this
repo's own seed data, source, or the Playwright specs written against it
(e2e/tests/) — not guessed. Run in order; each step names exactly what to
click and what you should see.

## Live AI generation — now working, opt-in

Four actions call the live Claude API (`app/core/claude.py`): regenerating
a scenario's narrative, **Complete Thread & Evaluate**, and the chat
composer's **Suggest pushback** / **Sufficiency check** buttons.

Blocker B3 (`prd/MeadowOps_progress.md`) is fully closed as of 2026-09-14:
a real adapter (`app.domain.claude_client_anthropic.AnthropicClaudeClient`)
is wired into `app.main.create_app` and verified live — both against the
domain functions directly and through the actual `/regenerate` and
`/complete` HTTP routes on a real running app (200, genuine Claude-generated
content, real DB writes). It's **opt-in**, not automatic — set both
`ANTHROPIC_API_KEY` (a real key) and `MEADOWOPS_CLAUDE_CLIENT_ENABLED=true`
in `.env` to turn it on (`.env.example` documents both; deliberately two
separate settings, not one, so a key merely sitting in a local/CI `.env`
never silently starts making live billed calls — see
`Settings.anthropic_api_key`'s own comment). The local dev `.env` has the
real key but **deliberately not** the enabled flag left on permanently —
leaving both set broke `tests/conftest.py`'s own test isolation (3 tests
that assert a clean 503-no-client path started making real, billed live
calls instead, found live while closing this blocker), confirming exactly
the risk that design decision was protecting against. **Turn the flag on
only for the duration of this walkthrough**
(`MEADOWOPS_CLAUDE_CLIENT_ENABLED=true uv run uvicorn app.main:create_app
--factory --port 8000`, or add the line to `.env` and remove it again
afterward), and confirm the key is genuinely non-blank first — a `.env`
line with `ANTHROPIC_API_KEY=` present-but-empty looks configured at a
glance and is not. Without both set, these four routes 503 cleanly rather
than hanging. If you'd rather not spend a live API call mid-demo, step 10
still names the manual alternative for narrative/evaluation (hand-typed
ground truth), the exact same code path Unit 29's QA harness and the full
backend test suite exercise against `MockClaudeClient`. Every other step
in this script uses only already-seeded data and no AI call at all.

## Setup (once)

```bash
# 1. Postgres (docker-compose.yml maps 5434 -> container's 5432)
docker compose up -d

# 2. Backend — migrate, seed, run
cd backend
uv run alembic upgrade head
uv run python -c "
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.core.config import Settings
from app.services.auth_seed import seed_initial_users
from app.services.baseline_data import seed_master_data
from app.services.simulation_clock_ops import seed_initial_world_state_and_clock
from app.services.exception_rule_defaults import seed_exception_rule_thresholds

settings = Settings()
engine = create_engine(settings.database_url)
with Session(engine) as session:
    seed_initial_users(session, settings)
    seed_master_data(session)
    seed_initial_world_state_and_clock(session)
    seed_exception_rule_thresholds(session)
    session.commit()
"
uv run uvicorn app.main:create_app --factory --reload --port 8000

# 3. Subsystem 1 (orbynadmin) — separate terminal
cd frontend/subsystem_1/orbynadmin
npm run dev -- -p 4001

# 4. Subsystem 2 (shadcn-dashboard) — separate terminal
cd frontend/subsystem_2/shadcn-dashboard/nextjs-version
npm run dev -- -p 4002
```

Credentials come from `.env`'s `MEADOWOPS_INITIAL_{ADMIN,ANALYST}_{EMAIL,PASSWORD}`
— the same two seeded accounts the E2E suite logs in as
(`e2e/global-setup.ts`). Do not improvise different accounts; no others
exist (PRD 5.1: exactly two users).

## Part 1 — Subsystem 1 (orbynadmin), Admin (Builder) role

1. Open `http://localhost:4001`. Unauthenticated, you land on
   `/login` (`e2e/tests/orbynadmin/login.spec.ts` proves this redirect).
   Sign in with the seeded admin account.

2. **Dashboard** (`/dashboard/logistics`) — four KPI cards render:
   **OTIF**, **Fill Rate**, **Order Cycle Time**, **Perfect Order Rate**
   (exactly these four — Days of Supply is deliberately a separate
   per-product/warehouse metric, not a fifth global card here; see
   `docs/schema-diagram.md`'s `live.days_of_supply_snapshot` and the
   Inventory drill-down in step 4).

3. **Customers** (`/customers`) — real seeded rows render in a table; type
   into the search box and confirm the list filters live.

4. **Inventory** (`/inventory`) → click any product row → its drill-down
   page shows that product's own Days of Supply history, satisfying
   S1-FR-3's "calculate and display... days of supply" without a
   dashboard-level card for it.

5. **Query Playground** (`/query`) — the Analyst-facing hard permission
   boundary made visible:
   - Click **Run** on the default statement
     (`select * from product limit 50;`). A row count and a `sku` column
     appear — this is running against the read-only `meadowops_sandbox`
     Postgres role, not the operational `live` schema (docs/data-flow.md
     §3). If this is the very first run since the database was created,
     click **Refresh sandbox** first — the `sandbox` schema has no tables
     until that runs once.
   - Replace the statement with `update product set sku = sku;` and click
     **Run** again. A confirmation dialog titled "Confirm before running"
     appears, showing a **write** badge. Click **Cancel** — nothing is
     executed. This is PRD 5.9's soft boundary (the hard boundary is the
     database role itself, proven in `backend/tests/infra/test_sandbox_boundary.py`).

6. **Admin → Query Log** (`/admin/query-log`, Builder-only) — every query
   run in step 5 is listed with its own text and timestamp (S1-FR-14 audit
   log).

7. **Chat** (`/chat`) — the Builder's inbox side of the persona-chat
   feature. If an Analyst message already exists from a prior session, the
   thread lists it here; otherwise this is naturally empty on a fresh
   database and that's the correct state to show, not a bug.

## Part 2 — Subsystem 1, Analyst role

8. Log out, sign back in with the seeded **analyst** account.
   - Dashboard and Customers render identically to step 2-3 (Analyst has
     view access).
   - Navigate directly to `/admin/query-log` — you are shown "You don't
     have access to this page." (`e2e/tests/orbynadmin-analyst/role-gate.spec.ts`).
     This is the role boundary that matters for the demo: the Analyst can
     see operational data but never the Builder's own tooling.

## Part 3 — Subsystem 2 (shadcn-dashboard), Builder-only

9. Open `http://localhost:4002`. Signing in with the **analyst** account
   is rejected at `/sign-in` with "This workspace is available to Builder
   (admin) accounts only" (`e2e/tests/subsystem2/auth.spec.ts`) — this
   workspace has no Analyst-facing surface at all, by design (S1-FR-15's
   inbox lives in orbynadmin instead). Sign in with the **admin** account.

   **Scenarios** (`/scenarios`) — on a fresh database this correctly shows
   an empty state ("No scenarios yet"); the status filter still navigates.
   An open exception must exist before you can create a scenario from one —
   the background scheduler (`app/domain/scheduler.py`) generates these
   automatically once the backend has been running for a few simulated
   ticks (S1-FR-1/4.2), so if `/scenarios/new`'s exception picker is empty,
   leave the backend running a little longer rather than improvising one.

   Click **New Scenario**, pick an open exception (the canonical seeded
   storyline is Supplier `S-004`'s drifting lead time — PRD 4.3), choose a
   type/competency/difficulty, and click **Create scenario**. Creating a
   scenario does **not** call Claude (`app/api/admin_scenarios.py`'s
   `create_scenario_route` is separate from `/regenerate`) — this step
   works identically with or without a live `ANTHROPIC_API_KEY`.

10. On the scenario's detail page (`/scenarios/[id]`):
    - **Regenerate narrative** calls the live Claude API. A real adapter
      exists (`app.domain.claude_client_anthropic.AnthropicClaudeClient`,
      Phase 4 blocker B3, closed 2026-09-14 — including a live-verified
      round trip through this exact route) and `app.main.create_app` wires
      it in when `Settings.claude_client_enabled` is true. The local dev
      `.env` has a genuine `ANTHROPIC_API_KEY` but leaves that flag off by
      default (see "Live AI generation" above for why) — set
      `MEADOWOPS_CLAUDE_CLIENT_ENABLED=true` before starting the backend to
      make this button work live; expect a few seconds' wait while the
      real model call completes. If you'd rather not spend a live call
      mid-demo, use the **Edit narrative** form instead and type ground
      truth by hand — this is the exact same code path Unit 29's QA
      harness itself uses to drive its own automated run
      (`tests/support/qa_harness.py`: "Ground truth here is hand-authored
      via PATCH .../ground-truth, not Claude-regenerated"), so it is not an
      improvised substitute — it's this project's own established way of
      running the loop without a live Claude call.
    - **Approve**, then **Activate** the scenario.
    - Switch to orbynadmin's **Chat** (`/chat`) as the Analyst (step 8's
      account) — the newly activated scenario's thread is now visible.
      Type a message as the Analyst; switch back to the admin session in
      Subsystem 2 and reply as the Builder. This exercises the same
      real-time WebSocket delivery both ends of the chat rely on, with no
      AI involved. `suggest-pushback`/`sufficiency-check` (Unit 23) still
      have no frontend UI (a documented deferral — neither is required to
      close the loop, both are advisory aids for the Builder while
      composing a pushback).
    - Back on the scenario detail page, under **Persona threads**, click
      **Complete Thread & Evaluate** for the thread you just messaged in
      (Unit 34) — this also calls the live Claude API and is live-verified
      the same way Regenerate narrative is above (a real 200 through this
      exact route, real Evaluation row written). `e2e/tests/subsystem2/
      evaluation.spec.ts` still seeds its own Evaluation row directly
      (`e2e/scripts/seed_evaluation_fixture.py`) rather than via this
      button, since a committed E2E spec shouldn't depend on live, billed
      API calls — that script's own docstring is the historical record of
      the bug this button no longer has.
    - With an evaluation in place, fill in and submit **Record human
      review** (reviewer name, agree/override, tier assessment notes) —
      the Builder standing in for the External Human Reviewer, who has no
      account of their own in this phase (PRD 14's Open Items).
    - Click **View Portfolio Export** to see the compiled document
      (scenario summary, full transcript, evaluation, human review) —
      empty reflection is expected and correct here (PRD 1.6 requires
      neither a completed monthly review nor real reflection content for
      Done).
    - Switch to orbynadmin's **Chat** as the Analyst again — the composer
      has been replaced by a seven-question reflection form now that the
      thread is completed (Unit 34). Fill in and submit it; the export
      above would now include it on a reload.

## Closing the loop

Reload orbynadmin's **Activity** page (`/activity`, Unit 24) as the admin.
Click **Propose Decision**, fill in an entity type/ID, title, and summary,
and submit — it renders here as a new Ledger entry with **Request
Clarification**/**Accept**/**Reject** actions (Unit 34). Accept it, then
**Mark Implemented**, then **Record Outcome** to walk it through its full
lifecycle live, in the UI, with no `curl`/`httpie` call needed. Absent any
proposed decision, `/activity`'s own empty state ("Ledger entries appear
here once a decision is proposed") is itself the correct, honest thing to
show — not a bug to explain away.

Everything demoed above — both roles, both frontends, the permission
boundary, the chat thread shared live across the API boundary, the full
evaluation → human review → portfolio export chain, and the full Ledger
decision lifecycle — is genuinely clickable end-to-end with zero
improvisation and (outside the one Claude-dependent step, called out
above) zero live AI dependency.
