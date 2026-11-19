#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/phase15-lib.sh"

phase15_compose stop phase15-api vss-ui media-intake alert-realtime alert-realtime-redis
"$PROJECT_ROOT/scripts/stop-phase15-gpu-worker.sh"
echo "Phase 15 app, real-time alert rules and control worker stopped; registry, audit, backups, images and active backend workloads are preserved."
