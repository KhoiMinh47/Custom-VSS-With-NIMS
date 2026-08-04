#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/phase11-lib.sh"
source "$PROJECT_ROOT/scripts/rtcv-lib.sh"
export VSS_UNSUPPORTED_HOST_OVERRIDE="ACKNOWLEDGED_BY_USER_2026-07-23"

# Reconcile CPU APIs before changing the GPU window.  This is intentionally
# GPU-profile-free and does not restart RT-CV.
"$PROJECT_ROOT/scripts/ensure-control-plane.sh"

cleanup_on_error() {
  phase11_stop_gpu_services
  "$PROJECT_ROOT/scripts/start-rtcv.sh" >/dev/null 2>&1 || true
}
trap cleanup_on_error ERR

"$PROJECT_ROOT/scripts/start-phase11.sh"
docker exec ntc-vss-phase07-rtsp-relay \
  python3 -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:39101/health/ready', timeout=3)"

# Preserve the credential-free relay while releasing RT-CV GPU memory.
rtcv_compose stop rtcv-metadata rt-cv

"$PROJECT_ROOT/.venv/bin/python" \
  "$PROJECT_ROOT/services/gpu-admission-controller/admission.py" grant \
  --profile direct_rt_vlm --lease "$PHASE11_LEASE"

export LLM_IMAGE_PINNED="nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2:1@sha256:a2f4a5aefe7dd0ff29bfd8d7081ce4977337d1b12081361af7b6283ff9a406b2"
export VLM_IMAGE_PINNED="nvcr.io/nim/nvidia/cosmos3-reasoner:1.7@sha256:19add3edaaa77c4030c75eb27d30939c29ca93807bb7af10a1876f05d520026c"
export LLM_PROFILE_ID="5cf34bab34141258d0cc836c66684642d3e3f32b4daaa2008e48bd289d6bc84b"
export VLM_PROFILE_ID="e55fdb44f41441032f546360d0dcf61caa8b39fa2852d31124c03953d01e1cb3"
"$PROJECT_ROOT/scripts/start-profile.sh" local-vlm

deadline=$((SECONDS + 600))
until curl --fail --silent --max-time 5 \
  http://127.0.0.1:30082/v1/health/ready >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "ERROR: cached Cosmos3 did not become ready for Phase 11." >&2
    exit 1
  fi
  sleep 5
done

phase11_compose --profile direct up -d rt-vlm
deadline=$((SECONDS + 300))
until curl --fail --silent --max-time 5 \
  http://127.0.0.1:39200/v1/ready >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    phase11_compose --profile direct ps
    echo "ERROR: VSS RT-VLM did not become ready." >&2
    exit 1
  fi
  sleep 5
done

"$PROJECT_ROOT/.venv/bin/python" \
  "$PROJECT_ROOT/scripts/register-phase11-stream.py" register
trap - ERR
echo "Phase 11 direct RT-VLM started for cam-01 only."
