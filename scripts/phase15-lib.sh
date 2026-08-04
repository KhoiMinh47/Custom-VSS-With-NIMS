#!/usr/bin/env bash
set -euo pipefail

PHASE15_PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PHASE15_COMPOSE_FILE="$PHASE15_PROJECT_ROOT/deploy/compose/phase15.compose.yml"

phase15_compose() {
  docker compose -f "$PHASE15_COMPOSE_FILE" "$@"
}

phase15_wait_http() {
  local url="$1" seconds="$2" label="$3"
  local deadline=$((SECONDS + seconds))
  until curl --fail --silent --max-time 5 "$url" >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      echo "ERROR: $label readiness deadline exceeded." >&2
      return 1
    fi
    sleep 2
  done
}
