#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INFRA_COMPOSE="$PROJECT_ROOT/deploy/compose/infra.compose.yml"
INFRA_ENV_FILE="${INFRA_ENV_FILE:-$PROJECT_ROOT/.secrets/infra.env}"

require_infra_env() {
  if [[ ! -f "$INFRA_ENV_FILE" ]]; then
    echo "ERROR: missing $INFRA_ENV_FILE"
    echo "Create it from .env.example and keep it outside version control."
    return 1
  fi

  if [[ "$(stat -c '%a' "$INFRA_ENV_FILE")" != "600" ]]; then
    echo "ERROR: $INFRA_ENV_FILE must have permission 600."
    return 1
  fi
}

infra_compose() {
  require_infra_env
  docker compose \
    --env-file "$INFRA_ENV_FILE" \
    -f "$INFRA_COMPOSE" \
    "$@"
}
