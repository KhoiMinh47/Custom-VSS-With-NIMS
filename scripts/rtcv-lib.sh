#!/usr/bin/env bash

set -euo pipefail

RTCV_PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RTCV_COMPOSE_FILE="$RTCV_PROJECT_ROOT/deploy/compose/rtcv.compose.yml"
RTCV_IMAGE="nvcr.io/nvidia/vss-core/vss-rt-cv:3.2.1@sha256:1a8b9879686f21cb6b9589d6139b5ac2eb960f1520aa3b4bb5f079d05fee9458"
RTCV_ENGINE_DIR="$RTCV_PROJECT_ROOT/.cache/tensorrt/GPU-59b09ac3-aa3a-a575-1d27-cd957dda3fc0/rtdetr/fp16"

rtcv_compose() {
  docker compose -f "$RTCV_COMPOSE_FILE" "$@"
}

rtcv_require_admission() {
  local forbidden running free total
  forbidden='nemotron|cosmos3|rt-embed|rt-vlm|retail-model'
  running="$(
    docker ps --format '{{.Names}} {{.Image}}' \
      | grep -E "$forbidden" \
      | grep -v 'ntc-vss-phase07' \
      | grep -v '^ntc-vss-phase11-rt-vlm-results ' || true
  )"
  if [[ -n "$running" ]]; then
    echo "ERROR: another GPU-heavy profile is running; Phase 07 admission denied." >&2
    return 1
  fi
  read -r free total < <(
    nvidia-smi --query-gpu=memory.free,memory.total --format=csv,noheader,nounits \
      | awk -F, 'NR==1 {gsub(/ /,""); print $1, $2}'
  )
  if (( free * 100 < total * 15 )); then
    echo "ERROR: GPU free-memory headroom is below the 15% admission threshold." >&2
    return 1
  fi
}

rtcv_json_get() {
  local url="$1"
  "$RTCV_PROJECT_ROOT/.venv/bin/python" - "$url" <<'PY'
import json
import sys
from urllib.request import urlopen

with urlopen(sys.argv[1], timeout=10) as response:
    print(json.dumps(json.load(response), separators=(",", ":")))
PY
}
