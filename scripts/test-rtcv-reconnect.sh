#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/rtcv-lib.sh"
evidence="$PROJECT_ROOT/artifacts/logs/phase07-rtcv-reconnect.txt"
outage_seconds="${RTCV_RECONNECT_OUTAGE_SECONDS:-30}"
mkdir -p "$(dirname "$evidence")"
exec > >(tee "$evidence") 2>&1

"$PROJECT_ROOT/scripts/healthcheck-rtcv.sh"
before="$(curl --fail --silent http://127.0.0.1:39000/api/v1/metrics \
  | "$PROJECT_ROOT/.venv/bin/python" -c \
    'import json,sys; print(json.load(sys.stdin)["metrics-info"]["stream-stats"][0]["frame_number"])')"
echo "deepstream_frame_before=$before"

rtcv_compose stop rtsp-relay
echo "relay_outage_started=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
sleep "$outage_seconds"
rtcv_compose start rtsp-relay
echo "relay_restarted=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

deadline=$((SECONDS + 180))
while (( SECONDS < deadline )); do
  state="$(curl --silent --max-time 5 http://127.0.0.1:39000/api/v1/metrics || true)"
  after="$(
    printf '%s' "$state" \
      | "$PROJECT_ROOT/.venv/bin/python" -c \
        'import json,sys; x=json.load(sys.stdin); print(x["metrics-info"]["stream-stats"][0]["frame_number"])' \
        2>/dev/null || echo 0
  )"
  if (( after > before )); then
    echo "deepstream_frame_after=$after"
    echo "reconnect_result=PASS"
    exit 0
  fi
  sleep 5
done

echo "ERROR: DeepStream frame processing did not resume after relay restart." >&2
exit 1
