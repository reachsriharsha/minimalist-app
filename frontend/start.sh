#!/usr/bin/env bash
# start.sh -- single entrypoint for running the frontend locally and (later) in Docker.
#
# Usage (from frontend/):
#   ./start.sh                     # runs `bun run dev` (Vite dev server with HMR)
#   ./start.sh dev                 # explicit dev mode; same as the default
#   ./start.sh build               # produce a production bundle in dist/
#   ./start.sh preview             # serve the built dist/ locally (static preview)
#   ./start.sh install             # run `bun install` against the committed lockfile
#   INSTALL=1 ./start.sh           # run `bun install` before the selected command
#
# Environment variables read:
#   HOST               (default 0.0.0.0; forwarded to Vite's --host flag)
#   PORT               (default 5173; forwarded to Vite's --port flag)
#   VITE_API_BASE_URL  (default http://localhost:8000; used by the dev-server proxy and baked
#                       into production builds as the backend base URL)
#   INSTALL            (default 0; when "1", `bun install` runs before dev/build/preview)
#
# Later, feat_infra_001 will invoke this same script as the container CMD so
# the local and containerized entrypoints do not diverge.

set -euo pipefail

# Resolve frontend/ regardless of where this script is invoked from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-5173}"
INSTALL="${INSTALL:-0}"

# Dispatch: optional first positional arg selects a subcommand.
cmd="${1:-dev}"
shift || true

run_install() {
  echo "[start.sh] running bun install"
  bun install
}

maybe_install() {
  if [[ "$INSTALL" == "1" ]]; then
    run_install
  fi
}

case "$cmd" in
  install)
    run_install
    ;;
  dev)
    maybe_install
    exec bun run dev --host "$HOST" --port "$PORT" "$@"
    ;;
  build)
    maybe_install
    exec bun run build "$@"
    ;;
  preview)
    maybe_install
    exec bun run preview --host "$HOST" --port "$PORT" "$@"
    ;;
  *)
    echo "[start.sh] unknown command: $cmd" >&2
    echo "usage: start.sh [dev|build|preview|install] [extra args...]" >&2
    exit 2
    ;;
esac
