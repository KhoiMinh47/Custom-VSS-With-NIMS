#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
output="$PROJECT_ROOT/runtime/backups/phase15/phase15-control-plane-$timestamp.tar.gz"
mkdir -p "$PROJECT_ROOT/runtime/backups/phase15"

tar -C "$PROJECT_ROOT" -czf "$output" \
  config/application/service-registry.json \
  config/cameras/cameras.hybrid.json \
  config/security/phase15-rbac.json \
  config/observability/phase15.json \
  config/ui/vss-ui.env \
  deploy/compose/phase15.compose.yml \
  schemas/openapi/phase15.openapi.json \
  apps/vss-ui \
  services/api/service.py \
  services/api/vss_ui.py \
  services/api/workspace.py \
  services/api/vlm_test_overlay.js \
  services/vlm-test \
  services/alert-verification/service.py \
  services/incidents/service.py \
  services/api/registry.py \
  services/api/security.py \
  services/api/configure_token.py \
  services/api/README.md \
  services/api/gpu_control.py \
  services/search/service.py \
  services/summarization/service.py \
  services/gpu-control-worker \
  tests/unit/test_phase12.py \
  tests/unit/test_phase13.py \
  tests/unit/test_phase15.py \
  tests/unit/test_vlm_test.py \
  scripts/backup-phase15.sh \
  scripts/capture-phase15-evidence.sh \
  scripts/healthcheck-phase15.sh \
  scripts/phase15-lib.sh \
  scripts/ensure-control-plane.sh \
  scripts/stop-profile.sh \
  scripts/start-phase11-direct.sh \
  scripts/start-phase13-vlm.sh \
  scripts/start-phase13-llm.sh \
  scripts/start-phase10-vlm.sh \
  scripts/stop-phase12.sh \
  scripts/start-phase15.sh \
  scripts/alert-realtime-start.py \
  scripts/stop-phase15.sh \
  scripts/test-phase15.sh \
  scripts/test-phase15-restore.sh \
  scripts/start-phase15-gpu-worker.sh \
  scripts/stop-phase15-gpu-worker.sh \
  docs/handoffs/PHASE-15-HANDOFF.md \
  docs/runbooks/phase15-app-recovery.md \
  PROJECT_STATE.md \
  runtime/phase15/audit
sha256sum "$output" >"$output.sha256"
printf '%s\n' "$output"
