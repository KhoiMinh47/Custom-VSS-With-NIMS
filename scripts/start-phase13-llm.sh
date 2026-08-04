#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/env.sh"
source "$PROJECT_ROOT/scripts/phase13-lib.sh"
lease="$PROJECT_ROOT/runtime/gpu-admission/phase13-llm.lease"
phase13_export_model_env

"$PROJECT_ROOT/scripts/ensure-control-plane.sh"
export LLM_MAX_MODEL_LEN="4096"
export LLM_KVCACHE_PERCENT="0.50"
export LLM_MAX_NUM_SEQS="1"
export LLM_MAX_NUM_BATCHED_TOKENS="4096"

phase13_stop_realtime_gpu
phase13_grant summarization_llm "$lease"
if ! "$PROJECT_ROOT/scripts/start-profile.sh" local-llm; then
  phase13_revoke "$lease"
  if [[ "${START_PHASE13_LLM_RESTORE_RTCV:-true}" == "true" ]]; then
    phase13_restore_realtime_gpu
  fi
  exit 1
fi
if ! phase13_wait_http "http://127.0.0.1:30081/v1/health/ready" 600 "Nemotron summary"; then
  "$PROJECT_ROOT/scripts/stop-profile.sh" local-llm
  phase13_revoke "$lease"
  if [[ "${START_PHASE13_LLM_RESTORE_RTCV:-true}" == "true" ]]; then
    phase13_restore_realtime_gpu
  fi
  exit 1
fi
echo "Phase 13 Nemotron summary/Q&A window is ready."
