#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output="$PROJECT_ROOT/artifacts/benchmarks/phase13-summarization"
mkdir -p "$output"

curl --fail --silent http://127.0.0.1:39410/api/v1/state \
  >"$output/service-state.json"
curl --fail --silent http://127.0.0.1:39410/api/v1/jobs \
  >"$output/jobs.json"
curl --fail --silent http://127.0.0.1:39410/metrics \
  >"$output/metrics.txt"
curl --fail --silent http://127.0.0.1:39410/dashboard \
  >"$output/dashboard.html"
docker inspect ntc-vss-phase13-summarization \
  --format '{{json .Mounts}}' >"$output/mounts.json"
docker logs --since 60m ntc-vss-phase13-summarization 2>&1 \
  | tail -500 >"$output/service.log"
docker logs --since 4h \
  ntc-vss-retail-poc-gpu-poc-cosmos3-1 2>&1 \
  | tail -1000 >"$PROJECT_ROOT/artifacts/logs/phase13-cosmos-caption-cache-and-inference.txt"
docker logs --since 4h \
  ntc-vss-retail-poc-gpu-poc-nemotron-1 2>&1 \
  | tail -1000 >"$PROJECT_ROOT/artifacts/logs/phase13-nemotron-summary-cache-and-inference.txt"
curl --fail --silent \
  -H 'Content-Type: application/json' \
  -d '{"size":0}' \
  http://127.0.0.1:9200/vss-captions/_search \
  >"$output/caption-index-count.json"
curl --fail --silent \
  -H 'Content-Type: application/json' \
  -d '{"size":0}' \
  http://127.0.0.1:9200/vss-summaries/_search \
  >"$output/summary-index-count.json"
curl --fail --silent http://127.0.0.1:9090/api/v1/targets \
  >"$output/prometheus-targets.json"
nvidia-smi \
  --query-gpu=timestamp,name,memory.total,memory.used,utilization.gpu,power.draw \
  --format=csv,noheader >"$output/gpu-final.csv"

if rg -n -i \
  '(ngc_api_key|camera_password|rtsp://[^[:space:]@]+:[^[:space:]@]+@)' \
  "$output" \
  "$PROJECT_ROOT/artifacts/logs/phase13-cosmos-caption-cache-and-inference.txt" \
  "$PROJECT_ROOT/artifacts/logs/phase13-nemotron-summary-cache-and-inference.txt"; then
  echo "ERROR: credential-like content found in captured Phase 13 evidence." >&2
  exit 1
fi
echo "Phase 13 secret-safe evidence captured under $output"
