#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
evidence="$PROJECT_ROOT/artifacts/logs/phase10-smoke.txt"
eval_dir="$PROJECT_ROOT/artifacts/evals/phase10"
candidate_file="$eval_dir/source-behavior-candidate.json"
mkdir -p "$PROJECT_ROOT/artifacts/logs" "$eval_dir"
exec > >(tee "$evidence") 2>&1

echo "phase=10"
echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
"$PROJECT_ROOT/.venv/bin/python" -m pytest -q "$PROJECT_ROOT/tests/unit/test_phase10.py"
"$PROJECT_ROOT/scripts/start-phase10.sh"

"$PROJECT_ROOT/.venv/bin/python" - "$candidate_file" <<'PY'
import json
import sys
from urllib.request import Request, urlopen

query = {
    "size": 1,
    "query": {
        "bool": {
            "filter": [
                {"term": {"candidate": True}},
                {"term": {"evaluation": False}},
            ]
        }
    },
    "sort": [{"@timestamp": {"order": "desc"}}],
}
request = Request(
    "http://127.0.0.1:9200/vss-behavior-events/_search",
    data=json.dumps(query).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urlopen(request, timeout=10) as response:
    hits = json.load(response).get("hits", {}).get("hits", [])
if not hits:
    raise SystemExit("ERROR: no real non-evaluation Phase 09 candidate is available")
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(hits[0]["_source"], handle)
print(f'source_candidate={hits[0]["_source"]["event_id"]}')
PY

curl --fail --silent --show-error \
  -H 'Content-Type: application/json' \
  --data-binary "@$candidate_file" \
  http://127.0.0.1:39121/api/v1/candidates \
  -o "$eval_dir/incident-submit.json"

"$PROJECT_ROOT/.venv/bin/python" - "$eval_dir" <<'PY'
import json
import sys
import time
from pathlib import Path
from urllib.request import urlopen

target = Path(sys.argv[1])
deadline = time.monotonic() + 90
while time.monotonic() < deadline:
    with urlopen("http://127.0.0.1:39121/api/v1/state", timeout=10) as response:
        state = json.load(response)
    incident = state.get("last_incident")
    if incident:
        break
    time.sleep(1)
else:
    raise SystemExit("ERROR: candidate did not produce a selected clip")
clip = Path("runtime/incidents/clips") / f'{incident["incident_id"]}.mp4'
assert clip.is_file() and clip.stat().st_size == incident["clip_bytes"]
assert b"ftyp" in clip.read_bytes()[:32]
(target / "incident-state.json").write_text(json.dumps(state, indent=2) + "\n")
print(
    f'incident_to_clip=PASS incident_id={incident["incident_id"]} '
    f'clip_bytes={incident["clip_bytes"]}'
)
PY

status="$(curl --silent --output "$PROJECT_ROOT/artifacts/logs/phase10-dashboard.html" \
  --write-out '%{http_code}' http://127.0.0.1:39120/dashboard)"
[[ "$status" == "200" ]]
grep -F 'Phase 10 alert verification' \
  "$PROJECT_ROOT/artifacts/logs/phase10-dashboard.html" >/dev/null
grep -F 'feedback_label' "$PROJECT_ROOT/artifacts/logs/phase10-dashboard.html" >/dev/null
echo "review_ui=PASS status=200"

if docker inspect ntc-vss-phase10-incidents ntc-vss-phase10-alert-verification \
  --format '{{range .Mounts}}{{println .Source}}{{end}}' \
  | grep -F "$PROJECT_ROOT/runtime/raw-video" >/dev/null; then
  echo "ERROR: Phase 10 must not mount raw video storage." >&2
  exit 1
fi
echo "plane_isolation=PASS selected_clip_api_only"

if docker logs ntc-vss-phase10-incidents 2>&1 \
  | grep -Eiq 'rtsp://[^/@[:space:]]+:[^/@[:space:]]+@'; then
  echo "ERROR: RTSP credential found in incident logs." >&2
  exit 1
fi
if docker logs ntc-vss-phase10-alert-verification 2>&1 \
  | grep -Eiq 'rtsp://[^/@[:space:]]+:[^/@[:space:]]+@'; then
  echo "ERROR: RTSP credential found in verification logs." >&2
  exit 1
fi
echo "secret_log_scan=PASS"

curl --fail --silent http://127.0.0.1:39120/api/v1/state \
  -o "$eval_dir/verifier-state.json"
curl --fail --silent http://127.0.0.1:39120/api/v1/evaluation \
  -o "$eval_dir/evaluation-report.json"
echo "completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
