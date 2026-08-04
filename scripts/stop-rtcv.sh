#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/rtcv-lib.sh"

rtcv_compose stop
echo "Stopped Phase 07 containers; images, model cache, TensorRT engines, broker data,"
echo "Elasticsearch metadata and all Phase 06 video data were preserved."
