#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/video-lib.sh"

video_compose config --quiet
video_compose up -d
"$PROJECT_ROOT/scripts/healthcheck-video-management.sh"
