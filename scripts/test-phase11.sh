#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
evidence="$PROJECT_ROOT/artifacts/logs/phase11-smoke.txt"
mkdir -p "$PROJECT_ROOT/artifacts/logs" \
  "$PROJECT_ROOT/artifacts/benchmarks/rt-vlm-alert"
exec > >(tee "$evidence") 2>&1

echo "phase=11"
echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
"$PROJECT_ROOT/.venv/bin/python" -m pytest -q \
  "$PROJECT_ROOT/tests/unit/test_phase11.py"
"$PROJECT_ROOT/scripts/start-phase11.sh"

for path in dashboard api/v1/alerts api/v1/evaluation api/v1/comparison api/v1/resources metrics; do
  status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
    "http://127.0.0.1:39210/$path")"
  [[ "$status" == "200" ]]
done
curl --fail --silent http://127.0.0.1:39210/dashboard \
  -o "$PROJECT_ROOT/artifacts/logs/phase11-dashboard.html"
grep -F 'Phase 11 direct RT-VLM' \
  "$PROJECT_ROOT/artifacts/logs/phase11-dashboard.html" >/dev/null
grep -F 'Camera live 720p' \
  "$PROJECT_ROOT/artifacts/logs/phase11-dashboard.html" >/dev/null
grep -F 'Asia/Ho_Chi_Minh' \
  "$PROJECT_ROOT/artifacts/logs/phase11-dashboard.html" >/dev/null
curl --fail --silent http://127.0.0.1:39210/api/v1/resources \
  | "$PROJECT_ROOT/.venv/bin/python" -c \
    'import json,sys; value=json.load(sys.stdin); assert value["available"] is True; assert "host" in value and "gpu" in value'
echo "review_ui=PASS"

if docker inspect ntc-vss-phase11-rt-vlm-results \
  --format '{{range .Mounts}}{{println .Source}}{{end}}' \
  | grep -F "$PROJECT_ROOT/runtime/raw-video" >/dev/null; then
  echo "ERROR: Phase 11 collector must not mount raw video." >&2
  exit 1
fi
if grep -Eiq 'rtsp://[^/@[:space:]]+:[^/@[:space:]]+@' \
  "$PROJECT_ROOT/artifacts/logs/phase11-dashboard.html"; then
  echo "ERROR: credential-like RTSP URI found in Phase 11 UI." >&2
  exit 1
fi
if docker logs ntc-vss-phase11-rt-vlm-results 2>&1 \
  | grep -Eiq 'rtsp://[^/@[:space:]]+:[^/@[:space:]]+@'; then
  echo "ERROR: credential-like RTSP URI found in Phase 11 logs." >&2
  exit 1
fi
echo "plane_isolation=PASS"
echo "secret_scan=PASS"
echo "completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
