#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
base_url="${CAMERA_LIVE_BASE_URL:-http://127.0.0.1:8090}"
evidence="$PROJECT_ROOT/artifacts/logs/phase07-ai-overlay-smoke.txt"
page="$PROJECT_ROOT/artifacts/logs/phase07-ai-overlay.html"
state_file="$PROJECT_ROOT/artifacts/logs/phase07-ai-overlay-state.json"
mkdir -p "$PROJECT_ROOT/artifacts/logs"
exec > >(tee "$evidence") 2>&1

"$PROJECT_ROOT/scripts/camera-live.sh" start
"$PROJECT_ROOT/scripts/healthcheck-rtcv.sh"

status="$(curl --silent --output "$page" --write-out '%{http_code}' \
  "$base_url/ai-overlay")"
if [[ "$status" != "200" ]]; then
  echo "ERROR: /ai-overlay returned HTTP $status." >&2
  exit 1
fi
if ! grep -F 'src="/mjpeg"' "$page" >/dev/null \
  || ! grep -F 'id="aiOverlay"' "$page" >/dev/null \
  || ! grep -F 'fetch("/api/ai-state"' "$page" >/dev/null; then
  echo "ERROR: AI overlay page is missing the MJPEG source or canvas layer." >&2
  exit 1
fi
echo "ai_overlay_http=PASS status=200 mjpeg_source=present canvas=present"

curl --fail --silent --show-error "$base_url/api/ai-state" -o "$state_file"
"$PROJECT_ROOT/.venv/bin/python" - "$state_file" <<'PY'
import json
import sys

state = json.load(open(sys.argv[1], encoding="utf-8"))
assert state["schema_version"] == "1.0.0"
assert state["store_id"] == "store-001"
assert state["camera_id"] == "cam-01"
assert state["ai_connected"] is True
assert isinstance(state["frame_counter"], int)
assert state["source_fps"] > 0
print(
    f'ai_state_contract=PASS status={state["ai_status"]} '
    f'frame_counter={state["frame_counter"]}'
)
PY

"$PROJECT_ROOT/.venv/bin/python" <<'PY'
import json
import time
from urllib.request import urlopen

def fetch(url):
    with urlopen(url, timeout=5) as response:
        return json.load(response)

start_state = fetch("http://127.0.0.1:39080/debug/state")
start_metrics = fetch("http://127.0.0.1:39000/api/v1/metrics")
start_frames = int(start_state["frames"])
start_counter = int(start_metrics["metrics-info"]["stream-stats"][0]["frame_number"])
deadline = time.monotonic() + 120
while time.monotonic() < deadline:
    state = fetch("http://127.0.0.1:39080/debug/state")
    metrics = fetch("http://127.0.0.1:39000/api/v1/metrics")
    counter = int(metrics["metrics-info"]["stream-stats"][0]["frame_number"])
    tracks = [
        value.get("track_id")
        for value in state.get("last_frame", {}).get("objects", [])
        if value.get("track_id")
    ]
    if int(state["frames"]) > start_frames and counter > start_counter and tracks:
        print(
            f'metadata_progress=PASS frames={start_frames}->{state["frames"]} '
            f'frame_counter={start_counter}->{counter} track_id={tracks[0]}'
        )
        break
    time.sleep(1)
else:
    raise SystemExit("ERROR: metadata frame/track ID did not advance within 120 seconds")
PY

if grep -Eiq 'rtsp://[^/@[:space:]]+:[^/@[:space:]]+@' \
  "$page" "$state_file" "$PROJECT_ROOT/runtime/logs/camera-live.log"; then
  echo "ERROR: credential-bearing RTSP URI found in UI HTML/state/log." >&2
  exit 1
fi
echo "ai_overlay_secret_scan=PASS"
