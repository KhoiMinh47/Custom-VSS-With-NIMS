#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Model-control OFF intentionally does not restore RT-CV; RT-CV is upload-only.
"$PROJECT_ROOT/scripts/stop-profile.sh" local-vlm
"$PROJECT_ROOT/.venv/bin/python" \
  "$PROJECT_ROOT/services/gpu-admission-controller/admission.py" \
  revoke --lease "$PROJECT_ROOT/runtime/gpu-admission/local-vlm.lease" >/dev/null
echo "Cosmos3 VLM stopped; RT-CV was not restored."
