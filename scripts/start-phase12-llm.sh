#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/env.sh"
source "$PROJECT_ROOT/scripts/phase12-lib.sh"
lease="$PROJECT_ROOT/runtime/gpu-admission/phase12-llm.lease"
export VSS_UNSUPPORTED_HOST_OVERRIDE="ACKNOWLEDGED_BY_USER_2026-07-23"
export LLM_IMAGE_PINNED="nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2:1@sha256:a2f4a5aefe7dd0ff29bfd8d7081ce4977337d1b12081361af7b6283ff9a406b2"
export VLM_IMAGE_PINNED="nvcr.io/nim/nvidia/cosmos3-reasoner:1.7@sha256:19add3edaaa77c4030c75eb27d30939c29ca93807bb7af10a1876f05d520026c"
export LLM_PROFILE_ID="5cf34bab34141258d0cc836c66684642d3e3f32b4daaa2008e48bd289d6bc84b"
export VLM_PROFILE_ID="e55fdb44f41441032f546360d0dcf61caa8b39fa2852d31124c03953d01e1cb3"
export LLM_MAX_MODEL_LEN="4096"
export LLM_KVCACHE_PERCENT="0.50"
export LLM_MAX_NUM_SEQS="1"
export LLM_MAX_NUM_BATCHED_TOKENS="4096"

phase12_stop_realtime_gpu
phase12_grant search_llm "$lease"
if ! "$PROJECT_ROOT/scripts/start-profile.sh" local-llm; then
  phase12_revoke "$lease"
  phase12_restore_realtime_gpu
  exit 1
fi
if ! phase12_wait_http "http://127.0.0.1:30081/v1/health/ready" 600 "Nemotron"; then
  "$PROJECT_ROOT/scripts/stop-profile.sh" local-llm
  phase12_revoke "$lease"
  phase12_restore_realtime_gpu
  exit 1
fi
echo "Phase 12 Nemotron query decomposition window is ready."
