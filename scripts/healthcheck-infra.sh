#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/infra-lib.sh"

required=(postgres elasticsearch kafka redis minio prometheus grafana)
deadline=$((SECONDS + ${INFRA_HEALTH_TIMEOUT_SECONDS:-300}))

while (( SECONDS < deadline )); do
  failed=0
  for service in "${required[@]}"; do
    container_id="$(infra_compose ps -q "$service")"
    if [[ -z "$container_id" ]]; then
      failed=1
      continue
    fi
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")"
    if [[ "$health" != "healthy" ]]; then
      failed=1
    fi
  done

  if (( failed == 0 )); then
    printf 'All infrastructure services are healthy: %s\n' "${required[*]}"
    exit 0
  fi
  sleep 5
done

infra_compose ps
echo "ERROR: infrastructure did not become healthy before timeout."
exit 1
