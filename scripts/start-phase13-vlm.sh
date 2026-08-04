#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/env.sh"
source "$PROJECT_ROOT/scripts/phase13-lib.sh"
lease="$PROJECT_ROOT/runtime/gpu-admission/phase13-vlm.lease"
phase13_export_model_env

"$PROJECT_ROOT/scripts/ensure-control-plane.sh"

phase13_stop_realtime_gpu
phase13_grant summarization_vlm "$lease"
if ! "$PROJECT_ROOT/scripts/start-profile.sh" local-vlm; then
  phase13_revoke "$lease"
  phase13_restore_realtime_gpu
  exit 1
fi
if ! phase13_wait_http "http://127.0.0.1:30082/v1/health/ready" 600 "Cosmos3 caption"; then
  "$PROJECT_ROOT/scripts/stop-profile.sh" local-vlm
  phase13_revoke "$lease"
  phase13_restore_realtime_gpu
  exit 1
fi
if ! "$PROJECT_ROOT/.venv/bin/python" \
  "$PROJECT_ROOT/services/gpu-admission-controller/admission.py" \
  verify-reserve; then
  "$PROJECT_ROOT/scripts/stop-profile.sh" local-vlm
  phase13_revoke "$lease"
  phase13_restore_realtime_gpu
  echo "ERROR: Cosmos3 became ready without preserving the 5 GiB GPU reserve." >&2
  exit 1
fi
echo "Phase 13 Cosmos3 caption window is ready."
