#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
archive="$(bash "$PROJECT_ROOT/scripts/backup-phase15.sh")"
restore_root="$(mktemp -d "$PROJECT_ROOT/.cache/tmp/phase15-restore.XXXXXX")"
trap 'rm -rf -- "$restore_root"' EXIT

tar -C "$restore_root" -xzf "$archive"
test -s "$restore_root/config/application/service-registry.json"
test -s "$restore_root/apps/vss-ui/README.md"
test -s "$restore_root/apps/vss-ui/SOURCE-MANIFEST.json"
test -s "$restore_root/config/ui/vss-ui.env"
test -s "$restore_root/services/api/service.py"
test -s "$restore_root/services/api/vss_ui.py"
test -s "$restore_root/services/api/workspace.py"
test -s "$restore_root/services/api/vlm_test_overlay.js"
test -s "$restore_root/services/vlm-test/service.py"
test -s "$restore_root/services/vlm-test/contracts.py"
test -s "$restore_root/services/alert-verification/service.py"
test -s "$restore_root/services/incidents/service.py"
test -s "$restore_root/services/api/gpu_control.py"
test -s "$restore_root/services/search/service.py"
test -s "$restore_root/services/summarization/service.py"
test -s "$restore_root/deploy/compose/phase15.compose.yml"
test -s "$restore_root/docs/handoffs/PHASE-15-HANDOFF.md"
test -s "$restore_root/services/gpu-control-worker/worker.py"
test -s "$restore_root/scripts/alert-realtime-start.py"
test -d "$restore_root/runtime/phase15/audit"
cmp "$PROJECT_ROOT/config/application/service-registry.json" \
  "$restore_root/config/application/service-registry.json"
cmp "$PROJECT_ROOT/apps/vss-ui/SOURCE-MANIFEST.json" \
  "$restore_root/apps/vss-ui/SOURCE-MANIFEST.json"
cmp "$PROJECT_ROOT/config/ui/vss-ui.env" \
  "$restore_root/config/ui/vss-ui.env"
cmp "$PROJECT_ROOT/services/api/service.py" \
  "$restore_root/services/api/service.py"
cmp "$PROJECT_ROOT/services/api/vss_ui.py" \
  "$restore_root/services/api/vss_ui.py"
cmp "$PROJECT_ROOT/services/api/workspace.py" \
  "$restore_root/services/api/workspace.py"
cmp "$PROJECT_ROOT/services/api/vlm_test_overlay.js" \
  "$restore_root/services/api/vlm_test_overlay.js"
cmp "$PROJECT_ROOT/services/vlm-test/service.py" \
  "$restore_root/services/vlm-test/service.py"
cmp "$PROJECT_ROOT/services/vlm-test/contracts.py" \
  "$restore_root/services/vlm-test/contracts.py"
cmp "$PROJECT_ROOT/services/search/service.py" \
  "$restore_root/services/search/service.py"
cmp "$PROJECT_ROOT/services/summarization/service.py" \
  "$restore_root/services/summarization/service.py"
cmp "$PROJECT_ROOT/deploy/compose/phase15.compose.yml" \
  "$restore_root/deploy/compose/phase15.compose.yml"
cmp "$PROJECT_ROOT/services/gpu-control-worker/worker.py" \
  "$restore_root/services/gpu-control-worker/worker.py"
cmp "$PROJECT_ROOT/scripts/alert-realtime-start.py" \
  "$restore_root/scripts/alert-realtime-start.py"
echo "Phase 15 backup extracted and verified in an isolated temporary directory."
