#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/env.sh"
source "$PROJECT_ROOT/scripts/infra-lib.sh"
source "$PROJECT_ROOT/scripts/phase13-lib.sh"

"$PROJECT_ROOT/scripts/healthcheck-infra.sh"
mkdir -p \
  "$PROJECT_ROOT/runtime/summarization/jobs" \
  "$PROJECT_ROOT/runtime/summarization/reports" \
  "$PROJECT_ROOT/docs/evals/summarization" \
  "$PROJECT_ROOT/artifacts/benchmarks/phase13-summarization"

infra_compose up --no-deps --force-recreate elasticsearch-init
phase13_compose config --quiet
phase13_compose up -d summarization
phase13_wait_http "http://127.0.0.1:39410/health/ready" 120 "Phase 13 summarization"
echo "Phase 13 CPU queue/API is ready at http://127.0.0.1:39410/dashboard"
