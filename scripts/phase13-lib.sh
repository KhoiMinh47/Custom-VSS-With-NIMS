#!/usr/bin/env bash
set -euo pipefail

PHASE13_PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PHASE13_COMPOSE_FILE="$PHASE13_PROJECT_ROOT/deploy/compose/phase13.compose.yml"

phase13_compose() {
  docker compose -f "$PHASE13_COMPOSE_FILE" "$@"
}

phase13_stop_realtime_gpu() {
  source "$PHASE13_PROJECT_ROOT/scripts/rtcv-lib.sh"
  rtcv_compose stop rtcv-metadata rt-cv >/dev/null
}

phase13_restore_realtime_gpu() {
  "$PHASE13_PROJECT_ROOT/scripts/start-rtcv.sh"
}

phase13_grant() {
  local profile="$1" lease="$2"
  "$PHASE13_PROJECT_ROOT/.venv/bin/python" \
    "$PHASE13_PROJECT_ROOT/services/gpu-admission-controller/admission.py" \
    grant --profile "$profile" --lease "$lease"
}

phase13_revoke() {
  local lease="$1"
  "$PHASE13_PROJECT_ROOT/.venv/bin/python" \
    "$PHASE13_PROJECT_ROOT/services/gpu-admission-controller/admission.py" \
    revoke --lease "$lease"
}

phase13_wait_http() {
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

phase13_export_model_env() {
  export VSS_UNSUPPORTED_HOST_OVERRIDE="ACKNOWLEDGED_BY_USER_2026-07-23"
  export VLM_COMPILATION_CONFIG='{"cudagraph_mode":"FULL_AND_PIECEWISE","compile_mm_encoder":false}'
  export LLM_IMAGE_PINNED="nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2:1@sha256:a2f4a5aefe7dd0ff29bfd8d7081ce4977337d1b12081361af7b6283ff9a406b2"
  export VLM_IMAGE_PINNED="nvcr.io/nim/nvidia/cosmos3-reasoner:1.7@sha256:19add3edaaa77c4030c75eb27d30939c29ca93807bb7af10a1876f05d520026c"
  export LLM_PROFILE_ID="5cf34bab34141258d0cc836c66684642d3e3f32b4daaa2008e48bd289d6bc84b"
  export VLM_PROFILE_ID="e55fdb44f41441032f546360d0dcf61caa8b39fa2852d31124c03953d01e1cb3"
}
