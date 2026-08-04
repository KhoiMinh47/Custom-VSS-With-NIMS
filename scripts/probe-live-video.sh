#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/video-lib.sh"
video_require_python

proxy_url="$(
  curl --fail --silent --max-time 10 \
    http://127.0.0.1:30888/vst/api/v1/sensor/streams \
    | "$VIDEO_PYTHON" -c \
      'import json,sys; d=json.load(sys.stdin); s=[x for w in d for v in w.values() for x in v if x.get("name")=="cam-01"]; print(s[0]["url"])'
)"

set +e
printf '%s\n' "$proxy_url" | docker exec -i ntc-vss-phase06-streamprocessing \
  bash -lc '
    IFS= read -r proxy_uri
    timeout 8 gst-launch-1.0 -q \
      rtspsrc location="$proxy_uri" protocols=tcp latency=100 ! \
      decodebin ! fakesink sync=false
    result=$?
    proxy_uri=
    exit "$result"
  '
result=$?
set -e
unset proxy_url

# timeout(1) returning 124 means the live pipeline remained active for the
# entire observation window. A clean EOS is also acceptable.
if [[ "$result" -ne 0 && "$result" -ne 124 ]]; then
  echo "ERROR: live RTSP probe failed with exit code $result." >&2
  exit 1
fi
echo "live_rtsp_probe=PASS"
