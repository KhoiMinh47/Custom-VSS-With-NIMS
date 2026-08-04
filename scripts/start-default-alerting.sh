#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/phase11-lib.sh"

# The stable single-GPU alerting profile is RT-CV/Behavior plus the durable
# Phase 10 incident queue. Local Cosmos3 is admitted only for a bounded
# verification window; direct RT-VLM remains an explicit operator action.
if curl --fail --silent --max-time 3 \
  http://127.0.0.1:39200/v1/ready >/dev/null 2>&1; then
  "$PROJECT_ROOT/.venv/bin/python" \
    "$PROJECT_ROOT/scripts/register-phase11-stream.py" unregister || true
fi
phase11_stop_gpu_services
"$PROJECT_ROOT/.venv/bin/python" \
  "$PROJECT_ROOT/services/gpu-admission-controller/admission.py" revoke \
  --lease "$PROJECT_ROOT/runtime/gpu-admission/local-vlm.lease" >/dev/null

if ! curl --fail --silent --max-time 5 \
  http://127.0.0.1:39080/health/ready >/dev/null 2>&1; then
  "$PROJECT_ROOT/scripts/start-rtcv.sh"
fi
"$PROJECT_ROOT/scripts/start-behavior-analytics.sh"
"$PROJECT_ROOT/scripts/start-phase10.sh"
"$PROJECT_ROOT/scripts/healthcheck-default-alerting.sh"

echo "Default alerting active: Phase 10 hybrid; Phase 11 direct RT-VLM is opt-in."
