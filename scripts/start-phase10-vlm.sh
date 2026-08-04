#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/env.sh"
source "$PROJECT_ROOT/scripts/rtcv-lib.sh"
lease="$PROJECT_ROOT/runtime/gpu-admission/local-vlm.lease"
export VSS_UNSUPPORTED_HOST_OVERRIDE="ACKNOWLEDGED_BY_USER_2026-07-23"

"$PROJECT_ROOT/scripts/ensure-control-plane.sh"

cleanup_failure() {
  "$PROJECT_ROOT/scripts/stop-profile.sh" local-vlm >/dev/null 2>&1 || true
  "$PROJECT_ROOT/.venv/bin/python" \
    "$PROJECT_ROOT/services/gpu-admission-controller/admission.py" \
    revoke --lease "$lease" >/dev/null 2>&1 || true
  if [[ "${START_PHASE10_VLM_RESTORE_RTCV:-true}" == "true" ]]; then
    "$PROJECT_ROOT/scripts/start-rtcv.sh" >/dev/null 2>&1 || true
  fi
}
trap cleanup_failure ERR

# Preserve the credential-free relay and video plane while releasing RT-CV
# memory for the bounded hybrid-verification window.
rtcv_compose stop rtcv-metadata rt-cv >/dev/null
"$PROJECT_ROOT/.venv/bin/python" \
  "$PROJECT_ROOT/services/gpu-admission-controller/admission.py" grant --lease "$lease"

export LLM_IMAGE_PINNED="nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2:1@sha256:a2f4a5aefe7dd0ff29bfd8d7081ce4977337d1b12081361af7b6283ff9a406b2"
export VLM_IMAGE_PINNED="nvcr.io/nim/nvidia/cosmos3-reasoner:1.7@sha256:19add3edaaa77c4030c75eb27d30939c29ca93807bb7af10a1876f05d520026c"
export LLM_PROFILE_ID="5cf34bab34141258d0cc836c66684642d3e3f32b4daaa2008e48bd289d6bc84b"
export VLM_PROFILE_ID="e55fdb44f41441032f546360d0dcf61caa8b39fa2852d31124c03953d01e1cb3"
# Restore the reviewed standard Cosmos3 profile. VLM Test must not inherit a
# temporary low-memory experiment from the caller's environment.
export VLM_GPU_MEMORY_UTILIZATION="0.65"
export VLM_MAX_MODEL_LEN="32768"
export VLM_MAX_NUM_SEQS="1"
export VLM_MAX_NUM_BATCHED_TOKENS="4096"

if ! "$PROJECT_ROOT/scripts/start-profile.sh" local-vlm; then
  cleanup_failure
  exit 1
fi

deadline=$((SECONDS + 600))
until curl --fail --silent --max-time 5 \
  http://127.0.0.1:30082/v1/health/ready >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "ERROR: cached Cosmos3 NIM did not become ready." >&2
    "$PROJECT_ROOT/scripts/stop-profile.sh" local-vlm
    cleanup_failure
    exit 1
  fi
  sleep 5
done
trap - ERR
echo "Phase 10 local Cosmos3 is ready under an admission lease."
