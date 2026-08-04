#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JOB_ID="${VLM_TEST_JOB_ID:-}"
[[ "$JOB_ID" =~ ^[0-9a-f]{64}$ ]] || { echo "ERROR: VLM_TEST_JOB_ID is invalid." >&2; exit 2; }

VLM_API="http://127.0.0.1:39520"

post_json() {
  local url="$1" body="$2"
  curl --fail --silent --show-error --max-time 30 \
    -H 'Content-Type: application/json' -X POST \
    --data-binary "$body" "$url"
}

json_status() {
  "$PROJECT_ROOT/.venv/bin/python" - "$1" <<'PY'
import json
import sys
print(json.loads(sys.argv[1]).get("status", ""))
PY
}

stop_vlm() {
  "$PROJECT_ROOT/scripts/stop-profile.sh" local-vlm >/dev/null 2>&1 || true
  "$PROJECT_ROOT/.venv/bin/python" \
    "$PROJECT_ROOT/services/gpu-admission-controller/admission.py" \
    revoke --lease "$PROJECT_ROOT/runtime/gpu-admission/local-vlm.lease" >/dev/null 2>&1 || true
}
trap stop_vlm EXIT

if ! "$PROJECT_ROOT/scripts/start-phase10-vlm.sh" >/dev/null; then
  exit 1
fi

if ! response="$(post_json "$VLM_API/api/v1/jobs/$JOB_ID/launch" '{}')"; then
  exit 1
fi
status="$(json_status "$response")"
if [[ "$status" != "queued_for_vlm" && "$status" != "waiting_for_gpu" && "$status" != "running" && "$status" != "completed" ]]; then
  exit 1
fi

for _attempt in $(seq 1 600); do
  if ! state="$(curl --fail --silent --show-error --max-time 10 "$VLM_API/api/v1/jobs/$JOB_ID")"; then
    exit 1
  fi
  status="$(json_status "$state")"
  case "$status" in
    completed) exit 0 ;;
    failed) exit 1 ;;
  esac
  sleep 1
done
exit 1
