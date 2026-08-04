#!/usr/bin/env bash
set -euo pipefail

PHASE10_PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PHASE10_COMPOSE_FILE="$PHASE10_PROJECT_ROOT/deploy/compose/phase10.compose.yml"

phase10_compose() {
  docker compose -f "$PHASE10_COMPOSE_FILE" "$@"
}
