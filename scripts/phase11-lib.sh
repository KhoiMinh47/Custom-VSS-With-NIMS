#!/usr/bin/env bash
set -euo pipefail

PHASE11_PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PHASE11_COMPOSE_FILE="$PHASE11_PROJECT_ROOT/deploy/compose/phase11.compose.yml"
PHASE11_LEASE="$PHASE11_PROJECT_ROOT/runtime/gpu-admission/direct-rt-vlm.lease"
PHASE11_RESOURCE_DIR="$PHASE11_PROJECT_ROOT/runtime/phase11-monitor"
PHASE11_RESOURCE_PID="$PHASE11_RESOURCE_DIR/resource-monitor.pid"
PHASE11_RESOURCE_JSON="$PHASE11_RESOURCE_DIR/resource-metrics.json"
PHASE11_RT_VLM_IMAGE="nvcr.io/nvidia/vss-core/vss-rt-vlm:3.2.1@sha256:5403e0c8fa8b149e7ad15ab1b063b78d610e7a50297dba6ca550ac5cc5ef9504"

phase11_compose() {
  docker compose -f "$PHASE11_COMPOSE_FILE" "$@"
}

phase11_revoke() {
  "$PHASE11_PROJECT_ROOT/.venv/bin/python" \
    "$PHASE11_PROJECT_ROOT/services/gpu-admission-controller/admission.py" \
    revoke --profile direct_rt_vlm --lease "$PHASE11_LEASE" >/dev/null
}

phase11_stop_gpu_services() {
  phase11_compose --profile direct stop rt-vlm >/dev/null 2>&1 || true
  "$PHASE11_PROJECT_ROOT/scripts/stop-profile.sh" local-vlm >/dev/null 2>&1 || true
  phase11_revoke
}

phase11_start_resource_monitor() {
  mkdir -p "$PHASE11_RESOURCE_DIR" "$PHASE11_PROJECT_ROOT/artifacts/logs"
  if [[ -f "$PHASE11_RESOURCE_PID" ]]; then
    local existing_pid
    existing_pid="$(<"$PHASE11_RESOURCE_PID")"
    if [[ "$existing_pid" =~ ^[0-9]+$ ]] \
      && kill -0 "$existing_pid" >/dev/null 2>&1 \
      && tr '\0' ' ' <"/proc/$existing_pid/cmdline" \
        | grep -F 'phase11-resource-monitor.py' >/dev/null; then
      return
    fi
  fi
  nohup "$PHASE11_PROJECT_ROOT/.venv/bin/python" \
    "$PHASE11_PROJECT_ROOT/scripts/phase11-resource-monitor.py" \
    --output "$PHASE11_RESOURCE_JSON" \
    --pid-file "$PHASE11_RESOURCE_PID" \
    >"$PHASE11_PROJECT_ROOT/artifacts/logs/phase11-resource-monitor.log" 2>&1 &
  local deadline=$((SECONDS + 15))
  until [[ -s "$PHASE11_RESOURCE_JSON" ]]; do
    if (( SECONDS >= deadline )); then
      echo "ERROR: Phase 11 resource monitor did not publish metrics." >&2
      return 1
    fi
    sleep 1
  done
}

phase11_stop_resource_monitor() {
  if [[ ! -f "$PHASE11_RESOURCE_PID" ]]; then
    return
  fi
  local monitor_pid
  monitor_pid="$(<"$PHASE11_RESOURCE_PID")"
  if [[ "$monitor_pid" =~ ^[0-9]+$ ]] \
    && kill -0 "$monitor_pid" >/dev/null 2>&1 \
    && tr '\0' ' ' <"/proc/$monitor_pid/cmdline" \
      | grep -F 'phase11-resource-monitor.py' >/dev/null; then
    kill "$monitor_pid"
    local deadline=$((SECONDS + 10))
    while kill -0 "$monitor_pid" >/dev/null 2>&1; do
      if (( SECONDS >= deadline )); then
        break
      fi
      sleep 1
    done
  fi
}
