#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JOB_ID="${VLM_TEST_JOB_ID:-}"
[[ "$JOB_ID" =~ ^[0-9a-f]{64}$ ]] || { echo "ERROR: VLM_TEST_JOB_ID is invalid." >&2; exit 2; }

VLM_API="http://127.0.0.1:39520"
RTCV_API="http://127.0.0.1:39620"
RTCV_COMPOSE_FILE="$PROJECT_ROOT/deploy/compose/rtcv-file-batch.compose.yml"
RTCV_LEASE="$PROJECT_ROOT/runtime/gpu-admission/vlm-test-rtcv.lease"

json_status() {
  "$PROJECT_ROOT/.venv/bin/python" - "$1" <<'PY'
import json
import sys
value = json.loads(sys.argv[1])
print(value.get("status", ""))
PY
}

json_candidate() {
  "$PROJECT_ROOT/.venv/bin/python" - "$1" <<'PY'
import json
import sys
value = json.loads(sys.argv[1])
candidate = value.get("candidate")
if not isinstance(candidate, dict):
    raise SystemExit(1)
print(json.dumps(candidate, separators=(",", ":")))
PY
}

post_json() {
  local url="$1" body="$2"
  curl --fail --silent --show-error --max-time 30 \
    -H 'Content-Type: application/json' -X POST \
    --data-binary "$body" "$url"
}

set_rtcv_status() {
  local status="$1" message="$2" body
  body="$("$PROJECT_ROOT/.venv/bin/python" - "$status" "$message" <<'PY'
import json
import sys
print(json.dumps({"status": sys.argv[1], "message": sys.argv[2]}, separators=(",", ":")))
PY
)"
  post_json "$VLM_API/api/v1/jobs/$JOB_ID/rtcv-status" "$body" >/dev/null
}

stop_batch() {
  docker compose -f "$RTCV_COMPOSE_FILE" stop rtcv-file-batch >/dev/null 2>&1 || true
  "$PROJECT_ROOT/.venv/bin/python" \
    "$PROJECT_ROOT/services/gpu-admission-controller/admission.py" \
    revoke --lease "$RTCV_LEASE" >/dev/null 2>&1 || true
}

stop_vlm() {
  "$PROJECT_ROOT/scripts/stop-profile.sh" local-vlm >/dev/null 2>&1 || true
  "$PROJECT_ROOT/.venv/bin/python" \
    "$PROJECT_ROOT/services/gpu-admission-controller/admission.py" \
    revoke --lease "$PROJECT_ROOT/runtime/gpu-admission/local-vlm.lease" >/dev/null 2>&1 || true
}

cleanup() {
  stop_vlm
  stop_batch
}
trap cleanup EXIT

set_rtcv_status running "RT-CV file batch is starting for this upload."

stop_batch

admission_rc=0
admission_json="$($PROJECT_ROOT/.venv/bin/python \
  "$PROJECT_ROOT/services/gpu-admission-controller/admission.py" \
  grant --profile rtcv_file_batch --lease "$RTCV_LEASE")" || admission_rc=$?
if [[ "$admission_rc" != "0" || "$(json_status "$admission_json")" != "granted" ]]; then
  set_rtcv_status failed "GPU admission denied the RT-CV file batch."
  exit 1
fi

if ! docker compose -f "$RTCV_COMPOSE_FILE" up -d rtcv-file-batch >/dev/null; then
  set_rtcv_status failed "RT-CV file batch container could not start."
  exit 1
fi
ready=0
for _attempt in $(seq 1 60); do
  if curl --fail --silent --show-error --max-time 5 "$RTCV_API/health/ready" >/dev/null; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" != "1" ]]; then
  set_rtcv_status failed "RT-CV file batch service did not become ready."
  exit 1
fi

if ! rtcv_response="$(post_json "$RTCV_API/api/v1/jobs/$JOB_ID/run" '{}')"; then
  set_rtcv_status failed "RT-CV file batch rejected this upload."
  exit 1
fi
if [[ "$(json_status "$rtcv_response")" != "starting" ]]; then
  set_rtcv_status failed "RT-CV file batch rejected this upload."
  exit 1
fi

rtcv_final=''
for _attempt in $(seq 1 1200); do
  rtcv_state="$(curl --fail --silent --show-error --max-time 10 "$RTCV_API/api/v1/jobs/$JOB_ID")" || {
    set_rtcv_status failed "RT-CV status could not be read."
    exit 1
  }
  rtcv_state_status="$(json_status "$rtcv_state")"
  case "$rtcv_state_status" in
    completed)
      rtcv_final="$rtcv_state"
      break
      ;;
    no_candidate)
      set_rtcv_status no_candidate "RT-CV completed but found no candidate event in this video."
      exit 0
      ;;
    failed)
      set_rtcv_status failed "RT-CV file batch failed while processing this upload."
      exit 1
      ;;
  esac
  sleep 1
done

if [[ -z "$rtcv_final" ]]; then
  set_rtcv_status failed "RT-CV file batch timed out."
  exit 1
fi

candidate="$(json_candidate "$rtcv_final")" || {
  set_rtcv_status failed "RT-CV completed without a valid candidate contract."
  exit 1
}
if ! post_json "$VLM_API/api/v1/jobs/$JOB_ID/candidate" "$candidate" >/dev/null; then
  set_rtcv_status failed "VLM-test service rejected the RT-CV candidate."
  exit 1
fi
set_rtcv_status completed "RT-CV candidate created. RT-CV is stopped; VLM is starting."

# The RT-CV lease and container are released before Cosmos3 is admitted. This
# is the serialized GPU hand-off required by the project architecture.
stop_batch
if ! "$PROJECT_ROOT/scripts/start-phase10-vlm.sh" >/dev/null; then
  post_json "$VLM_API/api/v1/jobs/$JOB_ID/rtcv-status" \
    '{"status":"failed","message":"VLM could not be admitted after RT-CV."}' >/dev/null || true
  exit 1
fi

if ! vlm_response="$(post_json "$VLM_API/api/v1/jobs/$JOB_ID/launch" '{}')"; then
  post_json "$VLM_API/api/v1/jobs/$JOB_ID/rtcv-status" \
    '{"status":"failed","message":"VLM launch request failed after RT-CV."}' >/dev/null || true
  exit 1
fi
vlm_response_status="$(json_status "$vlm_response")"
if [[ "$vlm_response_status" != "queued_for_vlm" && "$vlm_response_status" != "waiting_for_gpu" && "$vlm_response_status" != "running" && "$vlm_response_status" != "completed" ]]; then
  exit 1
fi

for _attempt in $(seq 1 600); do
  if ! vlm_state="$(curl --fail --silent --show-error --max-time 10 "$VLM_API/api/v1/jobs/$JOB_ID")"; then
    post_json "$VLM_API/api/v1/jobs/$JOB_ID/rtcv-status" \
      '{"status":"failed","message":"VLM status could not be read after RT-CV."}' >/dev/null || true
    exit 1
  fi
  vlm_state_status="$(json_status "$vlm_state")"
  case "$vlm_state_status" in
    completed)
      exit 0
      ;;
    failed)
      exit 1
      ;;
  esac
  sleep 1
done
post_json "$VLM_API/api/v1/jobs/$JOB_ID/rtcv-status" \
  '{"status":"failed","message":"VLM workflow timed out."}' >/dev/null || true
exit 1
