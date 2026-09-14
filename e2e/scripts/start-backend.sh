#!/usr/bin/env bash
# Boots the real FastAPI backend against the local Docker Compose Postgres
# (docker-compose.yml at repo root, already required for normal local dev)
# for the Playwright suite's webServer to point browsers at. Migrations and
# all four bootstrap seeds are idempotent (see their own docstrings in
# app/services/auth_seed.py, baseline_data.py, simulation_clock_ops.py,
# exception_rule_defaults.py), so re-running this against an already-seeded
# dev database is a safe no-op — this is the same recipe
# .github/workflows/backend-ci.yml uses against its own throwaway Postgres,
# just against the persistent local one instead.
#
# Found live, 2026-09-14: seed_exception_rule_thresholds was missing from
# this list entirely — never called anywhere outside individual backend unit
# tests (each seeds it as its own fixture), despite its own docstring's
# stale claim of being "exercised for real at migration/seed time." On a
# genuinely fresh database (CI's own throwaway Postgres service container,
# never a long-lived local dev DB that happened to get seeded once early on
# and kept since) this left live.exception_rule_threshold permanently
# empty, surfacing here as e2e/scripts/seed_evaluation_fixture.py's
# "baseline master data must be seeded first" assertion failing on
# evaluation.spec.ts/reflection.spec.ts — the first time those specs ever
# ran against a truly fresh database. Same gap existed in
# backend-ci.yml's identical seed step and docs/walkthrough-script.md's
# Setup section (both fixed alongside this file) — likely present on the
# live Railway/Neon deployment too, since B1's own deployment log names the
# same three seeds only.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR/backend"

# Local dev: real secrets live only in the gitignored repo-root .env. In CI
# (.github/workflows/e2e.yml) there is no such file — the job's own `env:`
# block already supplies every MEADOWOPS_* variable as CI-only placeholders,
# matching backend-ci.yml's established pattern.
if [ -f "$ROOT_DIR/.env" ]; then
  set -a
  source "$ROOT_DIR/.env"
  set +a
fi

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

exec uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
