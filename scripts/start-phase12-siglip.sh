#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/phase12-lib.sh"
lease="$PROJECT_ROOT/runtime/gpu-admission/phase12-siglip.lease"
engine_dir="$PROJECT_ROOT/.cache/tensorrt/GPU-59b09ac3-aa3a-a575-1d27-cd957dda3fc0/siglip2/fp16"
restored=false

cleanup_failure() {
  if [[ "$restored" == false ]]; then
    phase12_compose --profile siglip stop siglip-object-embedding >/dev/null 2>&1 || true
    phase12_revoke "$lease" >/dev/null 2>&1 || true
    phase12_restore_realtime_gpu || true
  fi
}
trap cleanup_failure ERR

"$PROJECT_ROOT/scripts/healthcheck-infra.sh"
mkdir -p "$engine_dir"
chmod 0777 "$engine_dir"
phase12_stop_realtime_gpu
phase12_grant siglip_object "$lease"
phase12_compose --profile siglip up -d siglip-object-embedding
phase12_wait_http "http://127.0.0.1:39321/api/v1/ready" 900 "SigLIP2"
deadline=$((SECONDS + 900))
until curl --fail --silent --max-time 30 \
  -H 'Content-Type: application/json' \
  -d '{"text_input":"phase12 readiness probe","model":""}' \
  http://127.0.0.1:39321/api/v1/generate_text_embeddings >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "ERROR: SigLIP2 text embedding probe did not become ready." >&2
    exit 1
  fi
  sleep 5
done
restored=true
trap - ERR
echo "Phase 12 SigLIP2 text/image embedding is ready under a serialized GPU lease."
