#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log_dir="$PROJECT_ROOT/artifacts/logs"
eval_dir="$PROJECT_ROOT/artifacts/evals/phase10"
mkdir -p "$log_dir" "$eval_dir"

curl --fail --silent http://127.0.0.1:39121/api/v1/state \
  -o "$eval_dir/incident-state-final.json"
curl --fail --silent http://127.0.0.1:39120/api/v1/state \
  -o "$eval_dir/verifier-state-final.json"
curl --fail --silent http://127.0.0.1:39120/api/v1/evaluation \
  -o "$eval_dir/evaluation-report-final.json"
curl --fail --silent http://127.0.0.1:39120/api/v1/alerts \
  -o "$eval_dir/verified-alerts-final.json"

docker logs ntc-vss-retail-poc-gpu-poc-cosmos3-1 2>&1 \
  | grep -E \
    'Skipping download, using cached copy|gpu_memory_utilization|Model loading took|server is up and ready|POST /v1/chat/completions' \
  | sed -E 's/(api[_-]?key|password)([=:][^ ,}]*)?/\1=[REDACTED]/Ig' \
  > "$log_dir/phase10-cosmos3-cache-and-inference.txt"

docker inspect ntc-vss-phase10-incidents ntc-vss-phase10-media-preparation \
  ntc-vss-phase10-alert-verification \
  --format '{{range .Mounts}}{{println .Source}}{{end}}' \
  > "$log_dir/phase10-container-mounts.txt"
if grep -F "$PROJECT_ROOT/runtime/raw-video" \
  "$log_dir/phase10-container-mounts.txt" >/dev/null; then
  echo "ERROR: Phase 10 raw-video mount detected." >&2
  exit 1
fi

if docker logs ntc-vss-phase10-incidents 2>&1 \
  | grep -Eiq 'rtsp://[^/@[:space:]]+:[^/@[:space:]]+@'; then
  echo "ERROR: credential-like RTSP URI found in incident logs." >&2
  exit 1
fi
if docker logs ntc-vss-phase10-alert-verification 2>&1 \
  | grep -Eiq 'rtsp://[^/@[:space:]]+:[^/@[:space:]]+@'; then
  echo "ERROR: credential-like RTSP URI found in verifier logs." >&2
  exit 1
fi

echo "Phase 10 evidence captured; plane isolation and secret scans PASS."
