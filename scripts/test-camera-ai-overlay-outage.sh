#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
base_url="${CAMERA_LIVE_BASE_URL:-http://127.0.0.1:8090}"
evidence="$PROJECT_ROOT/artifacts/logs/phase07-ai-overlay-outage.txt"
temporary="$(mktemp -d)"
restored=false

restore() {
  if [[ "$restored" != "true" ]]; then
    bash "$PROJECT_ROOT/scripts/start-rtcv.sh" >/dev/null
  fi
  rm -f "$temporary/before.mjpeg" "$temporary/during.mjpeg"
  rmdir "$temporary" 2>/dev/null || true
}
trap restore EXIT

mkdir -p "$PROJECT_ROOT/artifacts/logs"
exec > >(tee "$evidence") 2>&1
"$PROJECT_ROOT/scripts/camera-live.sh" start
"$PROJECT_ROOT/scripts/healthcheck-rtcv.sh"

capture_mjpeg() {
  local output="$1" result
  set +e
  curl --silent --show-error --max-time 3 "$base_url/mjpeg" -o "$output"
  result=$?
  set -e
  if [[ "$result" -ne 0 && "$result" -ne 28 ]]; then
    echo "ERROR: MJPEG capture failed with curl exit $result." >&2
    return 1
  fi
  [[ -s "$output" ]]
}

capture_mjpeg "$temporary/before.mjpeg"
before_bytes="$(stat -c '%s' "$temporary/before.mjpeg")"
bash "$PROJECT_ROOT/scripts/stop-rtcv.sh"

"$PROJECT_ROOT/.venv/bin/python" - "$base_url/api/ai-state" <<'PY'
import json
import sys
import time
from urllib.request import urlopen

deadline = time.monotonic() + 30
while time.monotonic() < deadline:
    with urlopen(sys.argv[1], timeout=5) as response:
        state = json.load(response)
    if state.get("ai_connected") is False and state.get("ai_status") == "unavailable":
        print(f'ai_outage_indicator=PASS message={state["status_message"]}')
        break
    time.sleep(1)
else:
    raise SystemExit("ERROR: UI did not report RT-CV disconnection")
PY

status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  "$base_url/ai-overlay")"
[[ "$status" == "200" ]]
capture_mjpeg "$temporary/during.mjpeg"
during_bytes="$(stat -c '%s' "$temporary/during.mjpeg")"
echo "video_during_ai_outage=PASS before_bytes=$before_bytes during_bytes=$during_bytes"

bash "$PROJECT_ROOT/scripts/start-rtcv.sh"
"$PROJECT_ROOT/scripts/healthcheck-rtcv.sh"
restored=true
"$PROJECT_ROOT/.venv/bin/python" - "$base_url/api/ai-state" <<'PY'
import json
import sys
from urllib.request import urlopen

with urlopen(sys.argv[1], timeout=5) as response:
    state = json.load(response)
assert state["ai_connected"] is True
print("ai_recovery_indicator=PASS")
PY
