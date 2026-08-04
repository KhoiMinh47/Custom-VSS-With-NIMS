#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/phase12-lib.sh"
"$PROJECT_ROOT/scripts/stop-profile.sh" local-llm
phase12_revoke "$PROJECT_ROOT/runtime/gpu-admission/phase12-llm.lease"
phase12_restore_realtime_gpu
echo "Nemotron stopped; decomposition evidence preserved and RT-CV restored."
