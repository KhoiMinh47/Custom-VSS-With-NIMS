#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/phase13-lib.sh"
"$PROJECT_ROOT/scripts/stop-profile.sh" local-llm
phase13_revoke "$PROJECT_ROOT/runtime/gpu-admission/phase13-llm.lease"
phase13_restore_realtime_gpu
echo "Phase 13 Nemotron stopped; summaries/reports preserved and RT-CV restored."
