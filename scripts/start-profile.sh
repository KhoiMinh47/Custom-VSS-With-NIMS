#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
profile="${1:-}"

case "$profile" in
  infra)
    exec "$PROJECT_ROOT/scripts/start-infra.sh"
    ;;
  local-llm|local-vlm)
    source "$PROJECT_ROOT/scripts/model-gate-lib.sh"
    source "$PROJECT_ROOT/scripts/env.sh"
    require_phase02_pass
    : "${LLM_IMAGE_PINNED:?Set pinned image digest}"
    : "${VLM_IMAGE_PINNED:?Set pinned image digest}"
    : "${LLM_PROFILE_ID:?Set verified profile ID}"
    : "${VLM_PROFILE_ID:?Set verified profile ID}"
    admission_profile="local_llm"
    [ "$profile" = "local-vlm" ] && admission_profile="local_vlm"
    "$PROJECT_ROOT/.venv/bin/python" \
      "$PROJECT_ROOT/services/gpu-admission-controller/admission.py" \
      check --profile "$admission_profile"
    docker compose \
      -f "$PROJECT_ROOT/deploy/overlays/single-gpu-poc.compose.yml" \
      --profile "$profile" \
      up -d
    ;;
  *)
    echo "Usage: $0 infra|local-llm|local-vlm"
    exit 2
    ;;
esac
