#!/usr/bin/env bash
# start.sh — single entrypoint for running the backend locally and (later) in Docker.
#
# Usage (from backend/):
#   ./start.sh                     # runs uvicorn on $HOST:$PORT (defaults 0.0.0.0:8000)
#   ./start.sh --reload            # dev mode with auto-reload
#   MIGRATE=1 ./start.sh           # run 'alembic upgrade head' before serving
#   ./start.sh migrate             # run migrations only, then exit
#   ./start.sh shell               # open a Python shell with the app context
#   ./start.sh pytest              # run the in-container pytest suite
#
# Environment variables read:
#   HOST      (default 0.0.0.0)
#   PORT      (default 8000)
#   MIGRATE   (default 0; when "1" migrations run before the server starts)
#   LOG_LEVEL (default INFO; passed through to uvicorn)
#
# Later, feat_infra_001 will invoke this same script as the container CMD so
# the local and containerized entrypoints do not diverge.

set -euo pipefail

# Resolve backend/ regardless of where this script is invoked from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"
MIGRATE="${MIGRATE:-0}"

# Dispatch: optional first positional arg selects a subcommand.
cmd="${1:-serve}"
shift || true

run_migrations() {
  echo "[start.sh] running alembic upgrade head"
  uv run alembic upgrade head
}

case "$cmd" in
  migrate)
    run_migrations
    ;;
  shell)
    uv run python "$@"
    ;;
  pytest)
    uv run pytest "$@"
    ;;
  serve)
    if [[ "$MIGRATE" == "1" ]]; then
      run_migrations
    fi
    exec uv run uvicorn app.main:app \
      --host "$HOST" \
      --port "$PORT" \
      --log-level "$(echo "$LOG_LEVEL" | tr '[:upper:]' '[:lower:]')" \
      "$@"
    ;;
  *)
    echo "[start.sh] unknown command: $cmd" >&2
    echo "usage: start.sh [serve|migrate|shell|pytest] [extra args...]" >&2
    exit 2
    ;;
esac
