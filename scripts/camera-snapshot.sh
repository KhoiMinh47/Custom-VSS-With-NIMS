#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CAMERA_ID="${CAMERA_ID:-physical-cam-01}"
SECRET_SERVICE="ntc-vss-retail-poc"
SECRET_TOOL="$(command -v secret-tool || true)"
KEYCTL="$(command -v keyctl || true)"
KERNEL_KEY_NAME="${SECRET_SERVICE}:v2:${CAMERA_ID}"
PYTHON="$PROJECT_ROOT/.venv/bin/python"
SECRET_AGENT="$PROJECT_ROOT/services/video-management/camera_secret_agent.py"
SECRET_SOCKET="$PROJECT_ROOT/runtime/secrets/camera-secret.sock"
SECRET_PID="$PROJECT_ROOT/runtime/secrets/camera-secret.pid"
CONTAINER="ntc-vss-phase06-streamprocessing"
TEMP_PATH="/tmp/ntc-vss-${CAMERA_ID}-snapshot.jpg"
OUTPUT="$PROJECT_ROOT/runtime/snapshots/${CAMERA_ID}-$(date -u +%Y%m%dT%H%M%SZ).jpg"

lookup() {
  if [[ -n "$SECRET_TOOL" ]] && "$SECRET_TOOL" lookup service "$SECRET_SERVICE" camera "$CAMERA_ID" 2>/dev/null; then
    return 0
  fi
  if [[ -n "$KEYCTL" ]]; then
    local key_id
    key_id="$("$KEYCTL" search @u user "$KERNEL_KEY_NAME" 2>/dev/null || true)"
    if [[ -n "$key_id" ]] && "$KEYCTL" pipe "$key_id" 2>/dev/null; then
      return 0
    fi
  fi
  "$PYTHON" "$SECRET_AGENT" get --socket "$SECRET_SOCKET" --pid "$SECRET_PID"
}

mkdir -p "$PROJECT_ROOT/runtime/snapshots"
proxy_uri="$("$PYTHON" - <<'PY'
import json
from urllib.request import urlopen

with urlopen("http://127.0.0.1:30888/vst/api/v1/sensor/streams", timeout=10) as response:
    wrappers = json.load(response)
for wrapper in wrappers:
    for values in wrapper.values():
        if not isinstance(values, list):
            continue
        for stream in values:
            if (
                isinstance(stream, dict)
                and stream.get("name") == "cam-01"
                and str(stream.get("url", "")).startswith("rtsp://")
            ):
                print(stream["url"])
                raise SystemExit(0)
raise SystemExit("VIOS returned no live proxy for cam-01")
PY
)"
printf '%s\n' "$proxy_uri" | docker exec -i "$CONTAINER" bash -lc '
  IFS= read -r camera_uri
  rm -f /tmp/ntc-vss-physical-cam-01-snapshot.jpg
  timeout 15 gst-launch-1.0 -q \
    rtspsrc location="$camera_uri" protocols=tcp latency=200 ! \
    decodebin ! nvvideoconvert ! video/x-raw,format=I420,width=2560,height=1440 ! \
    jpegenc quality=90 ! filesink location=/tmp/ntc-vss-physical-cam-01-snapshot.jpg \
    >/dev/null 2>&1 || true
  camera_uri=
'
unset proxy_uri
docker cp "$CONTAINER:$TEMP_PATH" "$OUTPUT" >/dev/null
if [[ ! -s "$OUTPUT" ]] || ! file "$OUTPUT" | grep -q 'JPEG image data'; then
  rm -f "$OUTPUT"
  echo "ERROR: camera snapshot was not produced." >&2
  exit 1
fi
echo "snapshot=$OUTPUT"
