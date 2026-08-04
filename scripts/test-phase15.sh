#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/env.sh"
source "$PROJECT_ROOT/scripts/phase15-lib.sh"

phase15_compose config --quiet
"$PROJECT_ROOT/.venv/bin/python" -m pytest -q "$PROJECT_ROOT/tests/unit/test_phase15.py"
"$PROJECT_ROOT/.venv/bin/python" -m pytest -q "$PROJECT_ROOT/tests/unit/test_vlm_test.py"
"$PROJECT_ROOT/.venv/bin/python" -m py_compile \
  "$PROJECT_ROOT/services/api/service.py" \
  "$PROJECT_ROOT/services/api/vss_ui.py" \
  "$PROJECT_ROOT/services/api/workspace.py" \
  "$PROJECT_ROOT/services/alert-verification/service.py" \
  "$PROJECT_ROOT/services/incidents/service.py" \
  "$PROJECT_ROOT/services/vlm-test/contracts.py" \
  "$PROJECT_ROOT/services/vlm-test/service.py"
test "$(git -C "$PROJECT_ROOT/third_party/video-search-and-summarization" rev-parse HEAD)" = \
  "7640d917047cf7b0fd3085eefb8282754b56bc94"
test "$(git -C "$PROJECT_ROOT/third_party/video-search-and-summarization" describe --tags --exact-match)" = "v3.2.1"
test -s "$PROJECT_ROOT/third_party/video-search-and-summarization/services/ui/apps/nv-metropolis-bp-vss-ui/components/Home.tsx"
test -s "$PROJECT_ROOT/third_party/video-search-and-summarization/services/ui/packages/nv-metropolis-bp-vss-ui/search/lib-src/SearchComponent.tsx"
bash "$PROJECT_ROOT/scripts/healthcheck-phase15.sh"
bash "$PROJECT_ROOT/scripts/test-phase15-restore.sh"

if rg -n -i \
  '(ngc_api_key|camera_password|rtsp://[^[:space:]@]+:[^[:space:]@]+@)' \
  "$PROJECT_ROOT/services/api" \
  "$PROJECT_ROOT/services/vlm-test" \
  "$PROJECT_ROOT/services/alert-verification" \
  "$PROJECT_ROOT/services/gpu-control-worker" \
  "$PROJECT_ROOT/services/mcp" \
  "$PROJECT_ROOT/services/agent" \
  "$PROJECT_ROOT/apps/vss-ui" \
  "$PROJECT_ROOT/config/ui" \
  "$PROJECT_ROOT/scripts/start-phase15-gpu-worker.sh" \
  "$PROJECT_ROOT/scripts/stop-phase15-gpu-worker.sh" \
  "$PROJECT_ROOT/config/application" \
  "$PROJECT_ROOT/config/security" \
  "$PROJECT_ROOT/deploy/compose/phase15.compose.yml"; then
  echo "ERROR: credential-like content found in Phase 15 source." >&2
  exit 1
fi

if rg -n 'runtime/raw-video|/var/run/docker.sock' \
  "$PROJECT_ROOT/services/api" \
  "$PROJECT_ROOT/services/vlm-test" \
  "$PROJECT_ROOT/services/alert-verification" \
  "$PROJECT_ROOT/services/gpu-control-worker" \
  "$PROJECT_ROOT/apps/vss-ui" \
  "$PROJECT_ROOT/config/ui" \
  "$PROJECT_ROOT/deploy/compose/phase15.compose.yml"; then
  echo "ERROR: Phase 15 mounts or references a forbidden control surface." >&2
  exit 1
fi
echo "Phase 15 registry, UI, RBAC, audit, isolation and restore tests passed."
