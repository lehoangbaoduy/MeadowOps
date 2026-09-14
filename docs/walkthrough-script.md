# Live Walkthrough Script

PRD §1.6 / Phase 4 exit criteria: "a live walkthrough can be given
end-to-end, using QA/synthetic data, without improvisation." Every route,
button label, and piece of text below was read directly from this
repo's own seed data, source, or the Playwright specs written against it
(e2e/tests/) — not guessed. Run in order; each step names exactly what to
click and what you should see.

## One honest gap, stated up front

Three actions in step 10 call the live Claude API (`app/core/claude.py`):
regenerating a scenario's narrative, and the chat composer's **Suggest
pushback** / **Sufficiency check** buttons. `ANTHROPIC_API_KEY` is unset in
this environment (`.env.example`: "absent during Build & Test; scenario
engine runs against a mock") — each of these three routes 503s cleanly
with no key configured, rather than hanging. **Do not attempt to demo live
AI generation without first confirming a real key is configured.** None of
the three is required to complete the loop: step 10 gives the manual
alternative for each (hand-typed ground truth, hand-typed chat replies),
using the exact same code paths Unit 29's QA harness and the full backend
test suite already exercise against `MockClaudeClient`. Every other step
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

settings = Settings()
engine = create_engine(settings.database_url)
with Session(engine) as session:
    seed_initial_users(session, settings)
    seed_master_data(session)
    seed_initial_world_state_and_clock(session)
    session.commit()
"
uv run uvicorn app.main:app --reload --port 8000

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
    - **Regenerate narrative** calls the live Claude API and needs a real
      key — with none configured (this environment, right now) it 503s
      cleanly rather than hanging. To continue the demo without a key,
      use the **Edit narrative** form instead and type ground truth by
      hand — this is the exact same code path Unit 29's QA harness itself
      uses to drive its own automated run (`tests/support/qa_harness.py`:
      "Ground truth here is hand-authored via PATCH .../ground-truth, not
      Claude-regenerated"), so it is not an improvised substitute — it's
      this project's own established way of running the loop without a
      live key.
    - **Approve**, then **Activate** the scenario.
    - Switch to orbynadmin's **Chat** (`/chat`) as the Analyst (step 8's
      account) — the newly activated scenario's thread is now visible.
      Type a message as the Analyst; switch back to the admin session in
      Subsystem 2 and reply as the Builder. This exercises the same
      real-time WebSocket delivery both ends of the chat rely on, with no
      AI involved — `suggest-pushback`/`sufficiency-check` (Unit 23) and
      the evaluation/human-review/portfolio routes (Units 25-26) are real,
      tested backend capabilities but have **no frontend UI at all** yet
      (a documented deferral, not something this script can demo live);
      likewise the Decision & Event Ledger's propose/accept/implement/
      outcome transitions are API-only. `docs/testing-report.md`'s
      backend-suite description and `tests/support/qa_harness.py` are
      where that part of the loop is actually exercised end-to-end.

## Closing the loop

Reload orbynadmin's **Activity** page (`/activity`, Unit 24) as the admin
— once a decision has actually been proposed via the API (as the QA
harness or a direct `curl`/`httpie` call against
`POST /api/scenarios/{id}/...` would do), it renders here as a Ledger
entry. Absent that, `/activity`'s own empty state ("Ledger entries appear
here once a decision is proposed") is itself the correct, honest thing to
show — not a bug to explain away.

This walkthrough deliberately stops at the boundary of what has a real UI
today. Everything demoed above — both roles, both frontends, the
permission boundary, the chat thread shared live across the API boundary —
is genuinely clickable end-to-end with zero improvisation and zero live AI
dependency; the remaining lifecycle steps are real and fully tested
(docs/testing-report.md), just API-only for now.
