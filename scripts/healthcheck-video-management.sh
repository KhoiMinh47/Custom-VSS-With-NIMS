#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/video-lib.sh"

deadline=$((SECONDS + 300))
required=(
  ntc-vss-phase06-postgres
  ntc-vss-phase06-redis
  ntc-vss-phase06-streamprocessing
  ntc-vss-phase06-sensor
  ntc-vss-phase06-ingress
)

while (( SECONDS < deadline )); do
  unhealthy=0
  for container in "${required[@]}"; do
    state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container" 2>/dev/null || true)"
    if [[ "$state" != "healthy" ]]; then
      unhealthy=1
      break
    fi
  done
  if [[ "$unhealthy" -eq 0 ]]; then
    printf 'Video services healthy: %s/%s\n' "${#required[@]}" "${#required[@]}"
    exit 0
  fi
  sleep 5
done

video_compose ps
echo "ERROR: video-management health deadline exceeded." >&2
exit 1
