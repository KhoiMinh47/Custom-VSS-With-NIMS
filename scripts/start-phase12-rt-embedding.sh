#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/phase12-lib.sh"
lease="$PROJECT_ROOT/runtime/gpu-admission/phase12-rt-embedding.lease"
restored=false

cleanup_failure() {
  if [[ "$restored" == false ]]; then
    phase12_compose --profile rt-embedding stop rt-embedding >/dev/null 2>&1 || true
    phase12_revoke "$lease" >/dev/null 2>&1 || true
    phase12_restore_realtime_gpu || true
  fi
}
trap cleanup_failure ERR

"$PROJECT_ROOT/scripts/healthcheck-infra.sh"
phase12_stop_realtime_gpu
phase12_grant rt_embedding "$lease"
phase12_compose --profile rt-embedding up -d rt-embedding
phase12_wait_http "http://127.0.0.1:39320/v1/ready" 600 "RT-Embedding"
restored=true
trap - ERR
echo "Phase 12 RT-Embedding is ready under a serialized GPU lease."
