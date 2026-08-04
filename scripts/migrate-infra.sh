#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/infra-lib.sh"

for migration in "$PROJECT_ROOT"/migrations/*.sql; do
  echo "Applying $(basename "$migration")"
  infra_compose exec -T postgres \
    psql \
      --set ON_ERROR_STOP=1 \
      --username "${POSTGRES_USER:-vss_app}" \
      --dbname "${POSTGRES_DB:-vss_control}" \
      < "$migration"
done
