# B1 (PRD 8.2): single always-on deployable process, backend only — the two
# Next.js frontends deploy separately (out of scope for this unit).
FROM python:3.12-slim AS base

RUN pip install --no-cache-dir uv

WORKDIR /app

# Dependencies first so they cache independently of app code changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY sql ./sql

ENV PATH="/app/.venv/bin:$PATH"

# Railway injects $PORT at runtime; uvicorn must bind to it, not a fixed port.
CMD ["sh", "-c", "uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
