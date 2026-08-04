#!/usr/bin/env bash
set -euo pipefail

BEHAVIOR_PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BEHAVIOR_COMPOSE_FILE="$BEHAVIOR_PROJECT_ROOT/deploy/compose/behavior-analytics.compose.yml"

behavior_compose() {
  docker compose -f "$BEHAVIOR_COMPOSE_FILE" "$@"
}
