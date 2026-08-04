#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/phase12-lib.sh"
"$PROJECT_ROOT/scripts/stop-profile.sh" local-vlm
phase12_revoke "$PROJECT_ROOT/runtime/gpu-admission/phase12-critic.lease"
phase12_restore_realtime_gpu
echo "Cosmos3 critic stopped; search evidence preserved and RT-CV restored."
