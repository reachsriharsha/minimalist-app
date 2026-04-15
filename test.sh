#!/usr/bin/env bash
# test.sh -- external REST functional test driver for the minimalist-app stack.
#
# Responsibilities:
#   1. Parse flags (--down, --no-up, -h/--help).
#   2. Probe TEST_BASE_URL/readyz; if not healthy and --no-up is not set,
#      invoke `make up` from the repo root, then wait for readiness.
#   3. Invoke `uv run pytest` inside tests/.
#   4. If --down is set, invoke `make down` after tests return (regardless
#      of pass/fail). Teardown errors never overwrite pytest's exit code.
#
# Environment:
#   TEST_BASE_URL       base URL of the backend (default http://localhost:8000)
#   READINESS_TIMEOUT   seconds to wait for /readyz before giving up (default 60)
#
# Exit code: pytest's exit code on pass/fail; 1 on readiness timeout; 2 on
# unknown flags.

set -euo pipefail

repo_root="$(cd "$(dirname "$0")" && pwd)"
base_url="${TEST_BASE_URL:-http://localhost:8000}"
readiness_timeout="${READINESS_TIMEOUT:-60}"
do_up=1
do_down=0

usage() {
  cat <<'EOF'
Usage: ./test.sh [--down] [--no-up] [-h|--help]

Flags:
  --no-up    Skip bringing the stack up; fail fast if /readyz is unreachable.
  --down     After tests, run `make down`. Pytest's exit code is preserved.
  -h,--help  Print this message and exit.

Environment:
  TEST_BASE_URL       Base URL for the backend. Default: http://localhost:8000
  READINESS_TIMEOUT   Seconds to wait for /readyz. Default: 60
EOF
}

for arg in "$@"; do
  case "$arg" in
    --no-up) do_up=0 ;;
    --down)  do_down=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[test.sh] unknown argument: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

probe_ready() {
  curl -fsS -o /dev/null -m 2 "${base_url}/readyz"
}

wait_for_ready() {
  local waited=0
  while ! probe_ready; do
    if [ "$waited" -ge "$readiness_timeout" ]; then
      echo "[test.sh] readiness timeout after ${readiness_timeout}s waiting for ${base_url}/readyz" >&2
      return 1
    fi
    echo "[test.sh] waiting for ${base_url}/readyz... ${waited}s"
    sleep 1
    waited=$((waited + 1))
  done
  return 0
}

if probe_ready; then
  echo "[test.sh] stack already healthy at ${base_url}"
else
  if [ "$do_up" -eq 1 ]; then
    echo "[test.sh] stack not ready at ${base_url}; running 'make up'..."
    (cd "$repo_root" && make up)
  else
    echo "[test.sh] stack not ready at ${base_url}; --no-up set, not bringing it up" >&2
  fi

  if ! wait_for_ready; then
    exit 1
  fi
fi

echo "[test.sh] stack ready at ${base_url}; running tests..."
rc=0
(cd "${repo_root}/tests" && TEST_BASE_URL="${base_url}" uv run pytest) || rc=$?

if [ "$do_down" -eq 1 ]; then
  echo "[test.sh] --down set; running 'make down'..."
  # Teardown failure must not overwrite pytest rc; swallow it intentionally.
  (cd "$repo_root" && make down) || echo "[test.sh] warning: 'make down' exited non-zero; preserving pytest rc=${rc}" >&2
fi

exit "$rc"
