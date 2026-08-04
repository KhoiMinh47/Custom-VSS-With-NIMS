#!/usr/bin/env bash
set -euo pipefail

PHASE12_PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PHASE12_COMPOSE_FILE="$PHASE12_PROJECT_ROOT/deploy/compose/phase12.compose.yml"

phase12_compose() {
  docker compose -f "$PHASE12_COMPOSE_FILE" "$@"
}

phase12_stop_realtime_gpu() {
  source "$PHASE12_PROJECT_ROOT/scripts/rtcv-lib.sh"
  rtcv_compose stop rtcv-metadata rt-cv >/dev/null
}

phase12_restore_realtime_gpu() {
  "$PHASE12_PROJECT_ROOT/scripts/start-rtcv.sh"
}

phase12_grant() {
  local profile="$1" lease="$2"
  "$PHASE12_PROJECT_ROOT/.venv/bin/python" \
    "$PHASE12_PROJECT_ROOT/services/gpu-admission-controller/admission.py" \
    grant --profile "$profile" --lease "$lease"
}

phase12_revoke() {
  local lease="$1"
  "$PHASE12_PROJECT_ROOT/.venv/bin/python" \
    "$PHASE12_PROJECT_ROOT/services/gpu-admission-controller/admission.py" \
    revoke --lease "$lease"
}

phase12_wait_http() {
  local url="$1" seconds="$2" label="$3"
  local deadline=$((SECONDS + seconds))
  until curl --fail --silent --max-time 5 "$url" >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      echo "ERROR: $label readiness deadline exceeded." >&2
      return 1
    fi
    sleep 5
  done
}
