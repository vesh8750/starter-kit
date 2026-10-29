# Multi-stage build.
#
# Stage 1 resolves dependencies from the lockfile into a self-contained virtualenv;
# stage 2 copies that venv into a clean runtime image. The result contains no build
# tools, no uv, no lockfile and no test code -- a smaller image with less to attack.
#
# Dependencies are installed before the application is copied so that editing source
# does not invalidate the dependency layer.

ARG PYTHON_VERSION=3.13

# ----------------------------------------------------------------- builder ---
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.23 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Cached layer: only re-runs when the lockfile or pyproject change.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# ----------------------------------------------------------------- runtime ---
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

# curl is used by the container healthcheck; nothing else is added.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --create-home app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1

WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app src/ ./src/
COPY --chown=app:app migrations/ ./migrations/
COPY --chown=app:app alembic.ini ./

USER app

EXPOSE 8000

# Readiness, not liveness: the orchestrator should stop routing traffic here when a
# dependency is down, and a separate liveness probe decides about restarts.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl --fail --silent http://localhost:8000/health/ready || exit 1

# Migrations are deliberately NOT run here. They are a separate, ordered deployment step
# (a job or an init container) -- running them per-replica races on every scale-up.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--no-access-log"]
