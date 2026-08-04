#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/env.sh"
source "$PROJECT_ROOT/scripts/infra-lib.sh"
source "$PROJECT_ROOT/scripts/phase12-lib.sh"

"$PROJECT_ROOT/scripts/healthcheck-infra.sh"
mkdir -p \
  "$PROJECT_ROOT/runtime/search/assets" \
  "$PROJECT_ROOT/runtime/search" \
  "$PROJECT_ROOT/docs/evals/search-results" \
  "$PROJECT_ROOT/artifacts/benchmarks/phase12-search"

infra_compose up --no-deps --force-recreate elasticsearch-init
phase12_compose config --quiet
phase12_compose up -d search
phase12_wait_http "http://127.0.0.1:39310/health/ready" 120 "Phase 12 search"
echo "Phase 12 CPU search API is ready at http://127.0.0.1:39310/dashboard"
