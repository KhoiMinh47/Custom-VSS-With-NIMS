#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
profile="${1:-}"

revoke_local_lease() {
  local lease="$PROJECT_ROOT/runtime/gpu-admission/$1"
  "$PROJECT_ROOT/.venv/bin/python" \
    "$PROJECT_ROOT/services/gpu-admission-controller/admission.py" \
    revoke --lease "$lease" >/dev/null 2>&1 || true
}

case "$profile" in
  infra)
    exec "$PROJECT_ROOT/scripts/stop-infra.sh"
    ;;
  local-llm)
    if docker container inspect ntc-vss-retail-poc-gpu-poc-nemotron-1 >/dev/null 2>&1; then
      docker stop ntc-vss-retail-poc-gpu-poc-nemotron-1
    fi
    revoke_local_lease local-llm.lease
    ;;
  local-vlm)
    if docker container inspect ntc-vss-retail-poc-gpu-poc-cosmos3-1 >/dev/null 2>&1; then
      docker stop ntc-vss-retail-poc-gpu-poc-cosmos3-1
    fi
    revoke_local_lease local-vlm.lease
    ;;
  *)
    echo "Usage: $0 infra|local-llm|local-vlm"
    exit 2
    ;;
esac
