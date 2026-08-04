#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/behavior-lib.sh"

"$PROJECT_ROOT/scripts/healthcheck-infra.sh"
"$PROJECT_ROOT/scripts/healthcheck-rtcv.sh"
mkdir -p "$PROJECT_ROOT/runtime/behavior-analytics"
ELASTICSEARCH_URL=http://127.0.0.1:9200 \
  CONFIG_DIR="$PROJECT_ROOT/config/elasticsearch" \
  sh "$PROJECT_ROOT/config/elasticsearch/bootstrap.sh"
behavior_compose config --quiet
behavior_compose up -d
curl --fail --silent --show-error -X POST \
  http://127.0.0.1:9090/-/reload >/dev/null
"$PROJECT_ROOT/scripts/healthcheck-behavior-analytics.sh"
