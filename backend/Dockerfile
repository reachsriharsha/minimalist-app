# backend/Dockerfile
#
# Multi-stage image for the FastAPI backend.
#
#   builder  -- uv-based dependency install, producing a .venv at /app/.venv
#   runtime  -- slim runtime with only the .venv + source, running as non-root
#
# The CMD path defers to backend/start.sh so the local (`./start.sh`) and
# containerized runs share one entrypoint. See backend/start.sh for the
# subcommand list (serve | migrate | shell | pytest).
#
# Build contexts:
#   - Compose invokes this with `context: ..` (repo root) and
#     `dockerfile: backend/Dockerfile`, so paths below are relative to the
#     repo root. When building by hand from backend/, use
#     `docker build -f Dockerfile ..`.

ARG PYTHON_VERSION=3.12

# -----------------------------------------------------------------------------
# Stage 1: builder
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

# uv version is pinned here; bump deliberately in a follow-up PR.
ARG UV_VERSION=0.5.11

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# Install uv. The official install script is the recommended path for slim
# images; it drops a static binary into /usr/local/bin/uv.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only the dependency manifests first so Docker layer cache survives
# unrelated source edits.
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./

# Install dependencies (no project install yet, project source is not here).
RUN uv sync --frozen --no-install-project --no-dev

# Now copy the project source and run a project install so `app` is importable
# from the .venv.
COPY backend/ ./
RUN uv sync --frozen --no-dev

# -----------------------------------------------------------------------------
# Stage 2: runtime
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:/usr/local/bin:${PATH}" \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# Install runtime-only OS deps. curl is used by the compose healthcheck so we
# intentionally keep it (small, well-known package).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 appuser \
    && useradd --system --uid 1000 --gid appuser --create-home --shell /bin/bash appuser

# Ship the uv binary so `start.sh` (which runs `uv run ...`) works inside the
# container. uv is a single static binary; copying it is cheap.
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv

WORKDIR /app

# Copy built venv and project source from the builder stage. Ownership is set
# so the non-root user can write to cache dirs under /app if needed.
COPY --from=builder --chown=appuser:appuser /app /app

USER appuser

EXPOSE 8000

# ENTRYPOINT + CMD split so compose can override just the command to run
# migrations one-shot: `command: ["migrate"]`.
ENTRYPOINT ["./start.sh"]
CMD ["serve"]
