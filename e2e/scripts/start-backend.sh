#!/usr/bin/env bash
# Boots the real FastAPI backend against the local Docker Compose Postgres
# (docker-compose.yml at repo root, already required for normal local dev)
# for the Playwright suite's webServer to point browsers at. Migrations and
# the three bootstrap seeds are all idempotent (see their own docstrings in
# app/services/auth_seed.py, baseline_data.py, simulation_clock_ops.py), so
# re-running this against an already-seeded dev database is a safe no-op —
# this is the same recipe .github/workflows/backend-ci.yml uses against its
# own throwaway Postgres, just against the persistent local one instead.
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

settings = Settings()
engine = create_engine(settings.database_url)
with Session(engine) as session:
    seed_initial_users(session, settings)
    seed_master_data(session)
    seed_initial_world_state_and_clock(session)
    session.commit()
"

exec uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
