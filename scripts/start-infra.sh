#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/infra-lib.sh"

mkdir -p \
  "$PROJECT_ROOT/runtime/postgres" \
  "$PROJECT_ROOT/runtime/elasticsearch" \
  "$PROJECT_ROOT/runtime/kafka" \
  "$PROJECT_ROOT/runtime/redis" \
  "$PROJECT_ROOT/runtime/minio" \
  "$PROJECT_ROOT/runtime/prometheus" \
  "$PROJECT_ROOT/runtime/grafana" \
  "$PROJECT_ROOT/runtime/backups/elasticsearch"

infra_compose config --quiet
infra_compose up -d --remove-orphans
"$PROJECT_ROOT/scripts/healthcheck-infra.sh"
