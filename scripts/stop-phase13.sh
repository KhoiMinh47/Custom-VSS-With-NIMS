#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/phase13-lib.sh"

"$PROJECT_ROOT/scripts/stop-profile.sh" local-vlm
"$PROJECT_ROOT/scripts/stop-profile.sh" local-llm
phase13_revoke "$PROJECT_ROOT/runtime/gpu-admission/phase13-vlm.lease" >/dev/null
phase13_revoke "$PROJECT_ROOT/runtime/gpu-admission/phase13-llm.lease" >/dev/null
phase13_compose stop summarization
phase13_restore_realtime_gpu
echo "Phase 13 stopped; jobs, captions, summaries, reports, caches and images preserved."
