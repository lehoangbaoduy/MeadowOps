#!/usr/bin/env bash
# Local CI-equivalent (PRD line 471, Unit 12/MEADOWOPS-INFRA-004: "Unit test
# suite scaffolded and running in CI (or a local equivalent)"). Runs the full
# backend test suite, the repo-root frontend structural checks, and a
# production build of both frontend templates. Exits non-zero on the first
# failure (tests/test_ci_script.py verifies this by sabotage-and-restore,
# not just by reading this file).
#
# Lint runs for visibility but does not block, for two separate pre-existing,
# out-of-scope-here reasons: orbynadmin has ~5 findings in vendored template
# files (noted since Unit 8); subsystem_2's ESLint setup has a pre-existing
# eslint-config-next/@eslint/eslintrc compatibility bug (circular JSON error
# on load) unrelated to this unit's own changes. See the progress doc (Unit
# 12) for both.
#
# Does not touch the shared dev database (no `alembic upgrade`/`downgrade`
# here) - a script run on every invocation is the wrong place for that, given
# the leaked-test-row history at Units 4/10.
#
# subsystem_2's own CLAUDE.md documents it as pnpm-managed - this script uses
# npm for it anyway (like Unit 7 already did), because pnpm crashes outright
# in this dev environment (`ERR_VM_DYNAMIC_IMPORT_CALLBACK_MISSING`, verified
# at Unit 12). `npm run <script>` alone doesn't trigger an implicit install,
# so it doesn't write a competing lockfile in practice - confirmed by running
# it repeatedly with no package-lock.json appearing.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "== backend: pytest (backend/tests) =="
( cd backend && set -a && source ../.env && set +a && .venv/bin/pytest )

echo "== repo root: pytest (tests/frontend, template-layout structural checks) =="
backend/.venv/bin/pytest tests/frontend/ -q

echo "== orbynadmin: lint (non-blocking, see header) =="
( cd frontend/subsystem_1/orbynadmin && npm run lint ) \
  || echo "[ci.sh] orbynadmin lint reported issues (non-blocking, see progress doc)"

echo "== orbynadmin: build =="
( cd frontend/subsystem_1/orbynadmin && npm run build )

echo "== subsystem_2: lint (non-blocking, see header) =="
( cd frontend/subsystem_2/shadcn-dashboard/nextjs-version && npm run lint ) \
  || echo "[ci.sh] subsystem_2 lint reported issues (non-blocking, see progress doc)"

echo "== subsystem_2: build =="
( cd frontend/subsystem_2/shadcn-dashboard/nextjs-version && npm run build )

echo "== all blocking checks passed =="
