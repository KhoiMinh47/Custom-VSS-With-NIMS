#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/phase12-lib.sh"
evidence="$PROJECT_ROOT/artifacts/logs/phase12-smoke.txt"

mkdir -p "$PROJECT_ROOT/artifacts/logs"
phase12_compose config --quiet
"$PROJECT_ROOT/.venv/bin/python" -m pytest -q \
  "$PROJECT_ROOT/tests/unit/test_phase12.py"
"$PROJECT_ROOT/scripts/healthcheck-phase12.sh"

curl --fail --silent http://127.0.0.1:39310/dashboard | grep -q "/api/v1/search"
state="$(curl --fail --silent http://127.0.0.1:39310/api/v1/state)"
decomposition="$(curl --fail --silent \
  -H 'Content-Type: application/json' \
  -d '{"query":"person walking with a backpack"}' \
  http://127.0.0.1:39310/api/v1/decompose)"
graceful="$(curl --fail --silent \
  -H 'Content-Type: application/json' \
  -d '{"query":"person entering a restricted area","route":"action","top_k":3,"critic_top_k":1}' \
  http://127.0.0.1:39310/api/v1/search)"

"$PROJECT_ROOT/.venv/bin/python" - "$state" "$decomposition" "$graceful" <<'PY' | tee "$evidence"
import json
import sys

state, decomposition, search = map(json.loads, sys.argv[1:])
assert state["video_documents"] >= 1
assert state["object_documents"] >= 1
assert decomposition["route"] in {"action", "attribute", "fusion"}
assert search["critic_status"] == "unavailable"
assert all("camera_id" in result for result in search["results"])
assert all(
    result.get("start_time") or result.get("frame_time")
    for result in search["results"]
)
assert all(result.get("asset_uri") for result in search["results"])
print(json.dumps({
    "phase12": "PASS",
    "video_documents": state["video_documents"],
    "object_documents": state["object_documents"],
    "critic_degradation": search["critic_status"],
}, separators=(",", ":")))
PY

if rg -n -i \
  '(ngc_api_key|camera_password|rtsp://[^[:space:]@]+:[^[:space:]@]+@)' \
  "$PROJECT_ROOT/services/search" \
  "$PROJECT_ROOT/services/rt-embedding" \
  "$PROJECT_ROOT/config/search" \
  "$PROJECT_ROOT/deploy/compose/phase12.compose.yml" \
  "$evidence"; then
  echo "ERROR: credential-like content found in Phase 12 artifacts." >&2
  exit 1
fi
if rg -n 'runtime/raw-video' \
  "$PROJECT_ROOT/services/search" \
  "$PROJECT_ROOT/services/rt-embedding" \
  "$PROJECT_ROOT/deploy/compose/phase12.compose.yml"; then
  echo "ERROR: Phase 12 code or Compose references raw storage." >&2
  exit 1
fi
echo "Phase 12 action/attribute/fusion/UI/isolation/degradation tests passed."
