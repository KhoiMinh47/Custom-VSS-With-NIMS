#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$PROJECT_ROOT/scripts/stop-profile.sh" local-vlm
"$PROJECT_ROOT/.venv/bin/python" \
  "$PROJECT_ROOT/services/gpu-admission-controller/admission.py" \
  revoke --lease "$PROJECT_ROOT/runtime/gpu-admission/local-vlm.lease"
"$PROJECT_ROOT/scripts/start-rtcv.sh"
echo "Phase 10 Cosmos3 stopped; model/image cache preserved and RT-CV restored."
