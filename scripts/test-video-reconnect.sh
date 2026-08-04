#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/video-lib.sh"
video_require_python

artifact="$PROJECT_ROOT/artifacts/logs/phase06-reconnect.txt"
mkdir -p "$(dirname "$artifact")"
exec > >(tee "$artifact") 2>&1
source_stopped=0

ensure_source_running() {
  if [[ "$source_stopped" -eq 1 ]]; then
    video_compose start simulated-cameras >/dev/null
  fi
}
trap ensure_source_running EXIT

online_count() {
  curl --fail --silent --max-time 10 \
    http://127.0.0.1:30888/vst/api/v1/sensor/status \
    | "$VIDEO_PYTHON" -c \
      'import json,sys; d=json.load(sys.stdin); print(sum(v.get("state") == "online" for v in d.values()))'
}

echo "phase=PHASE-06"
echo "schema_version=1.0.0"
echo "started_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
before_bytes="$(du -sb "$PROJECT_ROOT/runtime/raw-video" | awk '{print $1}')"
echo "recording_bytes_before=$before_bytes"
cam01_stream_id="$(
  curl --fail --silent --max-time 10 \
    http://127.0.0.1:30888/vst/api/v1/sensor/streams \
    | "$VIDEO_PYTHON" -c \
      'import json,sys; d=json.load(sys.stdin); s=[x for w in d for v in w.values() for x in v if x.get("name")=="cam-01"]; print(s[0]["streamId"])'
)"
before_timeline_end="$(
  curl --fail --silent --max-time 10 \
    "http://127.0.0.1:30888/vst/api/v1/storage/$cam01_stream_id/timelines" \
    | "$VIDEO_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)[-1]["endTime"])'
)"
echo "timeline_end_before=$before_timeline_end"

video_compose stop simulated-cameras
source_stopped=1
stable_samples=0
last_bytes=0
deadline=$((SECONDS + 120))
while (( SECONDS < deadline )); do
  current_bytes="$(du -sb "$PROJECT_ROOT/runtime/raw-video" | awk '{print $1}')"
  if [[ "$current_bytes" -eq "$last_bytes" ]]; then
    stable_samples=$((stable_samples + 1))
  else
    stable_samples=0
    last_bytes="$current_bytes"
  fi
  if [[ "$stable_samples" -ge 3 ]]; then
    break
  fi
  sleep 5
done
if [[ "$stable_samples" -lt 3 ]]; then
  echo "ERROR: recording did not quiesce after source loss." >&2
  exit 1
fi
echo "recording_bytes_while_stopped=$last_bytes"
echo "online_status_while_stopped=$(online_count || echo unavailable)"

video_compose start simulated-cameras
source_stopped=0
"$PROJECT_ROOT/scripts/healthcheck-video-management.sh"
deadline=$((SECONDS + 180))
while (( SECONDS < deadline )); do
  count="$(online_count || echo 0)"
  if [[ "$count" -eq 10 ]]; then
    echo "online_after_reconnect=$count"
    break
  fi
  sleep 5
done
if [[ "${count:-0}" -ne 10 ]]; then
  echo "ERROR: not all streams recovered after source restart." >&2
  exit 1
fi

deadline=$((SECONDS + 120))
after_bytes="$last_bytes"
after_timeline_end="$before_timeline_end"
while (( SECONDS < deadline )); do
  after_bytes="$(du -sb "$PROJECT_ROOT/runtime/raw-video" | awk '{print $1}')"
  after_timeline_end="$(
    curl --fail --silent --max-time 10 \
      "http://127.0.0.1:30888/vst/api/v1/storage/$cam01_stream_id/timelines" \
      | "$VIDEO_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)[-1]["endTime"])'
  )"
  if [[ "$after_bytes" -gt "$last_bytes" && "$after_timeline_end" > "$before_timeline_end" ]]; then
    break
  fi
  sleep 5
done
echo "recording_bytes_after=$after_bytes"
echo "timeline_end_after=$after_timeline_end"
if [[ "$after_bytes" -le "$last_bytes" || "$after_timeline_end" == "$before_timeline_end" ]]; then
  echo "ERROR: recording did not resume after reconnect." >&2
  exit 1
fi
echo "completed_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "result=PASS"
