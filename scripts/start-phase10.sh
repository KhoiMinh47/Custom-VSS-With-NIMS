#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/phase10-lib.sh"

"$PROJECT_ROOT/scripts/healthcheck-infra.sh"
"$PROJECT_ROOT/scripts/healthcheck-video-management.sh"
"$PROJECT_ROOT/scripts/healthcheck-behavior-analytics.sh"
mkdir -p "$PROJECT_ROOT/runtime/incidents/clips" "$PROJECT_ROOT/runtime/gpu-admission"
ELASTICSEARCH_URL=http://127.0.0.1:9200 \
  CONFIG_DIR="$PROJECT_ROOT/config/elasticsearch" \
  sh "$PROJECT_ROOT/config/elasticsearch/bootstrap.sh"
phase10_compose config --quiet
phase10_compose up -d
curl --fail --silent --show-error -X POST \
  http://127.0.0.1:9090/-/reload >/dev/null
"$PROJECT_ROOT/scripts/healthcheck-phase10.sh"
