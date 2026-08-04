#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Model-control OFF must revoke the Phase 13 lease used by the actual LLM
# launcher. It intentionally does not restore RT-CV; RT-CV is upload-only.
"$PROJECT_ROOT/scripts/stop-profile.sh" local-llm
"$PROJECT_ROOT/.venv/bin/python" \
  "$PROJECT_ROOT/services/gpu-admission-controller/admission.py" \
  revoke --lease "$PROJECT_ROOT/runtime/gpu-admission/phase13-llm.lease" >/dev/null
echo "Nemotron LLM stopped; RT-CV was not restored."
