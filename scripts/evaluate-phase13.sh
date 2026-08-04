#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cleanup() {
  "$PROJECT_ROOT/scripts/stop-profile.sh" local-vlm >/dev/null 2>&1 || true
  "$PROJECT_ROOT/scripts/stop-profile.sh" local-llm >/dev/null 2>&1 || true
  "$PROJECT_ROOT/.venv/bin/python" \
    "$PROJECT_ROOT/services/gpu-admission-controller/admission.py" revoke \
    --lease "$PROJECT_ROOT/runtime/gpu-admission/phase13-vlm.lease" >/dev/null 2>&1 || true
  "$PROJECT_ROOT/.venv/bin/python" \
    "$PROJECT_ROOT/services/gpu-admission-controller/admission.py" revoke \
    --lease "$PROJECT_ROOT/runtime/gpu-admission/phase13-llm.lease" >/dev/null 2>&1 || true
  "$PROJECT_ROOT/scripts/start-rtcv.sh" >/dev/null 2>&1 || true
}
trap cleanup EXIT

"$PROJECT_ROOT/scripts/start-phase13.sh"
"$PROJECT_ROOT/scripts/start-phase13-vlm.sh"
"$PROJECT_ROOT/.venv/bin/python" "$PROJECT_ROOT/scripts/run-phase13-workflow.py" caption
"$PROJECT_ROOT/scripts/stop-phase13-vlm.sh"
"$PROJECT_ROOT/scripts/start-phase13-llm.sh"
"$PROJECT_ROOT/.venv/bin/python" "$PROJECT_ROOT/scripts/run-phase13-workflow.py" summarize
"$PROJECT_ROOT/scripts/stop-phase13-llm.sh"
trap - EXIT
"$PROJECT_ROOT/scripts/healthcheck-phase13.sh"
"$PROJECT_ROOT/scripts/healthcheck-rtcv.sh"
echo "Phase 13 actual caption, hierarchical summary, Q&A and report evaluation completed."
