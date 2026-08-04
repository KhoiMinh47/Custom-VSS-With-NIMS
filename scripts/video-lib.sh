#!/usr/bin/env bash
set -euo pipefail

VIDEO_PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VIDEO_COMPOSE_FILE="$VIDEO_PROJECT_ROOT/deploy/compose/video-management.compose.yml"
VIDEO_REGISTRY="${VIDEO_REGISTRY:-$VIDEO_PROJECT_ROOT/config/cameras/cameras.hybrid.json}"
VIDEO_PYTHON="$VIDEO_PROJECT_ROOT/.venv/bin/python"

video_compose() {
  docker compose -f "$VIDEO_COMPOSE_FILE" "$@"
}

video_require_python() {
  if [[ ! -x "$VIDEO_PYTHON" ]]; then
    echo "ERROR: project-local Python is missing; run make bootstrap." >&2
    return 1
  fi
}
