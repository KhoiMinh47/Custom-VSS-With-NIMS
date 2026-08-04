#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/env.sh"

directories=(
  .cache/nim/nemotron-nano-9b-v2
  .cache/nim/cosmos3-nano-reasoner
  .cache/ngc
  .cache/huggingface/hub
  .cache/huggingface/transformers
  .cache/torch
  .cache/triton
  .cache/tensorrt
  .cache/pip
  .cache/uv/python
  .cache/corepack
  .cache/pnpm/home
  .cache/pnpm/store
  .cache/buildkit
  .cache/tmp
  .secrets
  models/rt-cv
  models/rtdetr
  models/vlm
  models/embedding
  models/siglip2
  models/cosmos-embed1
  models/retail
  models/retail-custom
  data/raw-samples
  data/clips
  data/snapshots
  data/thumbnails
  data/annotations
  data/test-videos
  runtime/postgres
  runtime/elasticsearch
  runtime/kafka
  runtime/redis
  runtime/minio
  runtime/vss
  runtime/vios
  runtime/clips
  runtime/incidents/clips
  runtime/gpu-admission
  runtime/rt-vlm-alert
  runtime/search
  runtime/search/assets
  runtime/summarization
  runtime/summarization/jobs
  runtime/summarization/reports
  runtime/grafana
  runtime/prometheus
  runtime/logs
  runtime/backups/elasticsearch
  deploy/compose
  deploy/configs
  deploy/dashboards
  deploy/elasticsearch
  deploy/kafka
  deploy/overlays
  deploy/reverse-proxy
  services/api-gateway
  services/camera-registry
  services/media-adapter
  services/scheduler
  services/incident-service
  services/search-service
  services/report-service
  services/retail-service
  services/gpu-admission-controller
  services/rt-vlm-alert
  services/mcp-server
  apps/web-dashboard
  integrations/nvidia-vss
  integrations/vios
  integrations/rt-cv
  integrations/rt-vlm
  integrations/rt-embedding
  integrations/triton
  schemas/jsonschema
  schemas/protobuf
  schemas/openapi
  tests/unit
  tests/integration
  tests/e2e
  tests/load
  tests/resilience
  tests/evaluation
  artifacts/preflight
  artifacts/manifests
  artifacts/benchmarks
  artifacts/benchmarks/rt-vlm-alert
  artifacts/benchmarks/phase12-search
  artifacts/benchmarks/phase13-summarization
  artifacts/benchmarks/phase15-unified-app
  artifacts/evals
  artifacts/logs
  artifacts/reports
  docs/api
  docs/operations
  docs/model-cards
  docs/security
  docs/runbooks
  docs/reports
  docs/evals/alert-verification
  docs/evals/search-results
  docs/evals/summarization
  runtime/phase15/audit
  runtime/phase15/gpu-control/requests
  runtime/phase15/gpu-control/processing
  runtime/phase15/gpu-control/completed
  runtime/backups/phase15
  .secrets/phase15
)

for directory in "${directories[@]}"; do
  mkdir -p "$PROJECT_ROOT/$directory"
done
chmod 700 "$PROJECT_ROOT/.secrets"
chmod 700 "$PROJECT_ROOT/.secrets/phase15"

if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv is required to create a project-local Python 3.12 environment."
  exit 1
fi

if [[ ! -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  uv venv --python 3.12 --seed "$PROJECT_ROOT/.venv"
fi

"$PROJECT_ROOT/.venv/bin/python" -c \
  'import sys; assert sys.version_info[:2] == (3, 12), sys.version'

echo "Project bootstrap complete: $PROJECT_ROOT"
