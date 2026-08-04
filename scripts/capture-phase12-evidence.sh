#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output="$PROJECT_ROOT/artifacts/benchmarks/phase12-search"
mkdir -p "$output"

curl --fail --silent http://127.0.0.1:39310/api/v1/state \
  >"$output/search-state.json"
curl --fail --silent http://127.0.0.1:39310/metrics \
  >"$output/search-metrics.txt"
curl --fail --silent http://127.0.0.1:39310/dashboard \
  >"$output/search-dashboard.html"
curl --fail --silent \
  -H 'Content-Type: application/json' \
  -d '{"query":"person sitting at a desk wearing a white shirt","route":"fusion","top_k":5,"critic_top_k":0}' \
  http://127.0.0.1:39310/api/v1/search \
  >"$output/fusion-search.json"
docker inspect \
  ntc-vss-phase12-search \
  --format '{{json .Mounts}}' >"$output/search-mounts.json"
docker logs --since 30m ntc-vss-phase12-search 2>&1 \
  | tail -500 >"$output/search-service.log"
nvidia-smi \
  --query-gpu=timestamp,name,memory.total,memory.used,utilization.gpu,power.draw \
  --format=csv,noheader >"$output/gpu-final.csv"

if rg -n -i \
  '(ngc_api_key|camera_password|rtsp://[^[:space:]@]+:[^[:space:]@]+@)' \
  "$output"; then
  echo "ERROR: credential-like content found in captured evidence." >&2
  exit 1
fi
echo "Phase 12 secret-safe evidence captured under $output"
