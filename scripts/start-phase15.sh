#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/infra-lib.sh"
source "$PROJECT_ROOT/scripts/phase15-lib.sh"

"$PROJECT_ROOT/scripts/healthcheck-infra.sh"
mkdir -p \
  "$PROJECT_ROOT/.secrets/phase15" \
  "$PROJECT_ROOT/runtime/phase15/audit" \
  "$PROJECT_ROOT/runtime/phase15/gpu-control/requests" \
  "$PROJECT_ROOT/runtime/phase15/gpu-control/processing" \
  "$PROJECT_ROOT/runtime/phase15/gpu-control/completed" \
  "$PROJECT_ROOT/runtime/phase15/vlm-test" \
  "$PROJECT_ROOT/runtime/backups/phase15" \
  "$PROJECT_ROOT/artifacts/benchmarks/phase15-unified-app"
chmod 700 "$PROJECT_ROOT/.secrets/phase15"

phase15_compose config --quiet
"$PROJECT_ROOT/scripts/start-phase15-gpu-worker.sh"
# Reconcile all browser-facing CPU dependencies while keeping GPU profiles
# untouched. The final phase15_compose call below is intentionally retained
# for this script's explicit readiness boundary.
"$PROJECT_ROOT/scripts/ensure-control-plane.sh"
phase15_compose up -d media-intake vlm-test vss-ui phase15-api
phase15_wait_http "http://127.0.0.1:39511/" 90 "NVIDIA VSS UI"
phase15_wait_http "http://127.0.0.1:39510/health/ready" 90 "Phase 15 unified app"
phase15_wait_http "http://127.0.0.1:39520/health/ready" 90 "Phase 15 VLM-test control plane"
if [[ -S "$PROJECT_ROOT/runtime/secrets/camera-secret.sock" ]]; then
  # The browser live presentation is a project-local, credential-brokered
  # service. Start it only when the approved camera secret lease exists.
  "$PROJECT_ROOT/scripts/camera-live.sh" start
else
  echo "camera_live=skipped reason=physical_camera_secret_unavailable"
fi
echo "NVIDIA VSS UI, Phase 15 gateway, VLM-test control plane and GPU worker are ready at http://127.0.0.1:39510/"
