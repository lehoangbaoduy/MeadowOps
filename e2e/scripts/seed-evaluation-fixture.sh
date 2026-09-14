#!/usr/bin/env bash
# Runs seed_evaluation_fixture.py against the already-running backend
# (playwright.config.ts's webServer guarantees it's up by the time any
# spec's test.beforeAll shells out to this) using the backend's own venv,
# same `uv run` + repo-root-.env-sourcing convention as
# e2e/scripts/start-backend.sh.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [ -f "$ROOT_DIR/.env" ]; then
  set -a
  source "$ROOT_DIR/.env"
  set +a
fi

cd "$ROOT_DIR/backend"
export PYTHONPATH="$ROOT_DIR/backend"
exec uv run python "$ROOT_DIR/e2e/scripts/seed_evaluation_fixture.py" "$@"
