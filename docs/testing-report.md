# Testing Report

PRD §1.6 / Phase 4 exit criteria: "a testing report summarizing coverage
and results." Counts below are regenerable, not narrated from memory —
see the exact command next to each. Snapshot taken 2026-09-13, current
branch `master`; backend count updated 2026-09-14 (Phase 4 blocker B3's
Anthropic adapter, 27 new tests total — 23 from the initial adapter, 4
more from the markdown-fence-stripping fix found via live verification).

## Suite inventory

| Suite | Count | Command | Runs in CI? |
|---|---|---|---|
| Backend unit/integration/architecture (`backend/tests/`) | 1311 | `cd backend && uv run --frozen pytest -q` | Yes — `.github/workflows/backend-ci.yml` |
| Repo-root frontend structural checks (`tests/frontend/`) | 23 | `cd backend && uv run --frozen pytest ../tests/frontend -q` | Yes — `backend-ci.yml`, "Run repo-root frontend structural checks" step |
| Playwright E2E (`e2e/tests/`) | 20 | `cd e2e && npx playwright test` | Yes — `.github/workflows/e2e.yml`, its own job |
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

## Unit 34's UI now has real E2E coverage (closed 2026-09-14)

Initially shipped verified only statically (types, lint, production
build) — no backend/DB configuration was available in that session to
boot the stack for a live click-through. Closed in a follow-up pass, with
a real local stack booted and all 7 new specs run live and repeatedly
(not just written and assumed to pass): `e2e/tests/orbynadmin/
ledger-actions.spec.ts` (2 tests — the full propose → accept → implement →
outcome lifecycle, plus reject), `e2e/tests/subsystem2/evaluation.spec.ts`
(3 tests — the evaluation/human-review/portfolio-export panel), and
`e2e/tests/orbynadmin-analyst/reflection.spec.ts` (2 tests — the Analyst's
reflection form, including the 409-as-already-submitted path).

Getting there surfaced a real, previously-unknown finding: `app.main.
create_app` hardcoded `app.state.claude_client = None` unconditionally at
the time (Phase 4 blocker B3) — no code path, even with a real
`ANTHROPIC_API_KEY` configured, made `POST .../complete` succeed against a
running app. **Since fixed — see the "Phase 4 blocker B3" section below**;
this paragraph is a historical record of what U34 found, not current
behavior. `e2e/scripts/seed_evaluation_fixture.py` still works
around this the same way `tests/support/qa_harness.py`'s own
`complete_thread` already does for the backend suite — scripting the
Evaluation row directly (plus one ExceptionFlag insert, since no route
creates one and the scheduler that normally would is disabled locally)
rather than depending on a live Claude call. Also caught and fixed:
`ScenariosPage`'s own empty-state E2E test assumed a scenario-free
database, which Unit 34's own fixture-creating specs now violate — refiltered
to `status=cancelled` (genuinely, deterministically empty) rather than the
unfiltered list.

## Phase 4 blocker B3: real Anthropic adapter (closed 2026-09-14)

`app.domain.claude_client_anthropic.AnthropicClaudeClient` now implements
`ClaudeClient` against the real `anthropic` SDK package, wired into
`app.main.create_app` behind a new opt-in `Settings.claude_client_enabled`
(default `False` — see that field's own comment for why "a key is present"
alone can't be the switch, given `tests/conftest.py` loads the repo-root
`.env`, key included, into every backend test process). 23 new tests:
config validation (`tests/core/test_config.py`), `create_app`'s own wiring
decision (`tests/core/test_claude_client_wiring.py`), and the adapter
itself (`tests/domain/test_claude_client_anthropic.py`) — the last exercised
against the real installed `anthropic` package's own exception types
(`anthropic.APITimeoutError`/`APIStatusError`/`APIConnectionError`/
`RateLimitError`/`InternalServerError`), not hand-rolled stand-ins, since
the adapter's most important property (upstream error text never reaching
`ClaudeAPIError`'s own message, per `scenario_generation.
ScenarioGenerationFailedError`'s own pre-existing docstring — that message
flows straight into an HTTP 502 detail the Builder's browser sees) can only
be checked against the SDK's real `str(exc)` behavior.

**Closed for real, same day, once the user supplied a genuine
`ANTHROPIC_API_KEY`.** (Before that: the repo-root `.env`'s key was present
but **blank**, not the real key an earlier session's notes had assumed —
caught a real gap in this unit's own `Settings` validator, an `is
None`-only check would have let `claude_client_enabled=True` through with
a blank key rather than failing fast at construction; fixed to also reject
an empty/whitespace-only key, with its own regression test.)

With a real key in place, `tests/domain/test_claude_client_anthropic_smoke.py`
(the PRD-line-373 "periodic live-call smoke test," still
`pytest.mark.skipif`-gated behind `MEADOWOPS_RUN_LIVE_CLAUDE_SMOKE_TEST=1`
so it never runs or spends money as part of a normal suite run) passed
immediately. But driving the real domain pipelines live — not just a raw
ping/pong — surfaced a genuine, previously-latent bug: `claude-sonnet-4-5`
routinely wraps its JSON response in a ` ```json ... ``` ` markdown fence
despite every one of `scenario_generation`/`evaluation`/`persona_chat`'s
own prompts explicitly instructing "no markdown fences." `MockClaudeClient`
never produces this shape, so none of the 23 tests written before a real
key existed could have caught it — `generate_scenario_narrative`'s first
live call failed with `response is not valid JSON: Expecting value: line 1
column 1 (char 0)`. Fixed in one place, `AnthropicClaudeClient.create_message`
(not in each of the three domain-layer parsers, since this is a real-API
quirk the domain layer shouldn't need to know about) — conservative by
construction, only strips a fence wrapping the *entire* response, so
content that merely mentions a code sample mid-text is untouched. 4 new
regression tests (27 total for this blocker).

Re-verified live, in order of increasing integration depth, after the fix:
domain functions directly (`generate_scenario_narrative`,
`generate_evaluation`, `suggest_pushback_message`, `run_sufficiency_check`
— all four AI call sites, all parse cleanly), then the actual running app
booted with `claude_client_enabled=true` and `POST .../regenerate` /
`POST .../complete` driven for real through the live HTTP routes — both
returned 200 with genuine Claude-generated content and real DB writes.
This is the verification PRD §10's "evaluation pipeline runs end-to-end
unattended" line asks for; see `prd/MeadowOps_progress.md`'s B3 entry for
the full detail, including a note that the verification's own thread rows
are now a permanent (harmless) addition to the local dev DB — `chat.
chat_message`'s immutability trigger blocked cleanup by design, same
precedent as U34's own E2E fixture-seeding pollution noted below.

**Separately noticed, not fixed here**: the full backend suite currently
shows 3 pre-existing failures in `tests/services/test_evaluation_service.py
::TestResolveDifficultyForCluster` (confirmed via `git stash` to predate
this unit's changes) — traced to real `Evaluation` rows for the
`analysis_diagnosis` competency cluster left behind in the shared local
dev Postgres by U34's own E2E fixture-seeding work earlier the same day
(`e2e/scripts/seed_evaluation_fixture.py`, which commits real rows rather
than rolling them back). `test_evaluation_service.py`'s own `session`
fixture connects to that same real database and only cleans up its own
`User` rows, not `Scenario`/`Evaluation` rows, so it silently assumed a
cluster-clean table that U34's own work invalidated. Local-dev-only (CI
runs against a fresh database per workflow), and not touched here — the
polluting rows may be exactly the seeded demo data `docs/walkthrough-
script.md` expects to still be there, so deleting them without asking
first would be the wrong call.

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

The 20 Playwright specs are deliberately not a re-test of backend logic —
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
