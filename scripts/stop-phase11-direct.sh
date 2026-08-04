#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/phase11-lib.sh"

if curl --fail --silent --max-time 3 \
  http://127.0.0.1:39200/v1/ready >/dev/null 2>&1; then
  "$PROJECT_ROOT/.venv/bin/python" \
    "$PROJECT_ROOT/scripts/register-phase11-stream.py" unregister || true
fi
phase11_stop_gpu_services
"$PROJECT_ROOT/scripts/start-rtcv.sh"
echo "Phase 11 direct mode stopped; RT-CV restored and caches preserved."
