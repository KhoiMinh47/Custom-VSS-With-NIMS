#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="$PROJECT_ROOT/artifacts/benchmarks/rt-vlm-alert"
mkdir -p "$target" "$PROJECT_ROOT/artifacts/logs"

curl --fail --silent http://127.0.0.1:39210/api/v1/state \
  -o "$target/collector-state-final.json"
curl --fail --silent http://127.0.0.1:39210/api/v1/alerts \
  -o "$target/direct-alerts-final.json"
curl --fail --silent http://127.0.0.1:39210/api/v1/evaluation \
  -o "$target/evaluation-final.json"
curl --fail --silent http://127.0.0.1:39210/api/v1/comparison \
  -o "$target/comparison-final.json"

docker inspect ntc-vss-phase11-rt-vlm-results \
  --format '{{range .Mounts}}{{println .Source}}{{end}}' \
  > "$PROJECT_ROOT/artifacts/logs/phase11-container-mounts.txt"
if grep -F "$PROJECT_ROOT/runtime/raw-video" \
  "$PROJECT_ROOT/artifacts/logs/phase11-container-mounts.txt" >/dev/null; then
  echo "ERROR: Phase 11 raw-video mount detected." >&2
  exit 1
fi
if docker logs ntc-vss-phase11-rt-vlm-results 2>&1 \
  | grep -Eiq 'rtsp://[^/@[:space:]]+:[^/@[:space:]]+@'; then
  echo "ERROR: credential-like RTSP URI found in collector logs." >&2
  exit 1
fi
echo "Phase 11 evidence captured; plane isolation and secret scans PASS."
