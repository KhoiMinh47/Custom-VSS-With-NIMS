#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/rtcv-lib.sh"

required=(
  ntc-vss-phase07-rtsp-relay
  ntc-vss-phase07-rtcv
  ntc-vss-phase07-metadata
)
deadline=$((SECONDS + 180))
while true; do
  unhealthy=""
  for container in "${required[@]}"; do
    state="$(
      docker inspect \
        --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
        "$container" 2>/dev/null || true
    )"
    if [[ "$state" != "healthy" ]]; then
      unhealthy="$container:$state"
      break
    fi
  done
  if [[ -z "$unhealthy" ]]; then
    break
  fi
  if (( SECONDS >= deadline )); then
    echo "ERROR: Phase 07 health deadline exceeded ($unhealthy)." >&2
    exit 1
  fi
  sleep 5
done

"$PROJECT_ROOT/.venv/bin/python" - <<'PY'
import json
from urllib.request import urlopen

with urlopen(
    "http://127.0.0.1:39000/api/v1/stream/get-stream-info", timeout=10
) as response:
    stream_info = json.load(response).get("stream-info", {})
    streams = stream_info.get("stream-info", stream_info.get("stream-list", []))
if len(streams) != 1 or streams[0].get("camera_id") != "cam-01":
    raise SystemExit("ERROR: Phase 07 must have exactly one source: cam-01")
with urlopen("http://127.0.0.1:39080/health/ready", timeout=10) as response:
    ready = json.load(response)
if ready.get("status") != "ready":
    raise SystemExit("ERROR: metadata service is not ready")
with urlopen(
    "http://127.0.0.1:9200/mdx-raw/_count?q=camera_id:cam-01", timeout=10
) as response:
    count = int(json.load(response)["count"])
if count < 1:
    raise SystemExit("ERROR: Elasticsearch contains no cam-01 RT-CV document")
print(f"Phase 07 healthy: sources=1 camera_id=cam-01 indexed_documents={count}")
PY
