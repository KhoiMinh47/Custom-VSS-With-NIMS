#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
evidence="$PROJECT_ROOT/artifacts/logs/phase09-behavior-smoke.txt"
eval_dir="$PROJECT_ROOT/artifacts/evals/phase09"
mkdir -p "$PROJECT_ROOT/artifacts/logs" "$eval_dir"
exec > >(tee "$evidence") 2>&1

echo "phase=09"
echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
"$PROJECT_ROOT/scripts/start-behavior-analytics.sh"
"$PROJECT_ROOT/.venv/bin/python" \
  "$PROJECT_ROOT/scripts/evaluate-behavior-analytics.py" "$eval_dir"

while IFS= read -r frame; do
  printf 'phase09-evaluation|%s\n' "$frame"
done < "$eval_dir/synthetic-frames.jsonl" \
  | docker exec -i ntc-vss-retail-poc-kafka-1 \
      /opt/kafka/bin/kafka-console-producer.sh \
      --bootstrap-server kafka:9092 \
      --topic vss.rt-cv.frames \
      --property parse.key=true \
      --property 'key.separator=|'

"$PROJECT_ROOT/.venv/bin/python" - "$eval_dir/evaluation-report.json" <<'PY'
import json
import sys
import time
from urllib.request import Request, urlopen

report = json.load(open(sys.argv[1], encoding="utf-8"))
expected = set(report["expected_event_types"])
deadline = time.monotonic() + 45
observed = set()
while time.monotonic() < deadline:
    query = {
        "size": 200,
        "query": {
            "bool": {
                "filter": [
                    {"term": {"evaluation": True}},
                    {"term": {"evaluation_run_id": report["run_id"]}},
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
    observed = {hit["_source"]["event_type"] for hit in hits}
    if expected <= observed:
        break
    time.sleep(1)
else:
    raise SystemExit(f"ERROR: missing persisted event types: {sorted(expected - observed)}")
print(f"broker_to_elasticsearch=PASS event_types={len(expected)}")
PY

status="$(curl --silent --output "$PROJECT_ROOT/artifacts/logs/phase09-dashboard.html" \
  --write-out '%{http_code}' http://127.0.0.1:39110/dashboard)"
[[ "$status" == "200" ]]
grep -F 'Phase 09 behavior analytics' \
  "$PROJECT_ROOT/artifacts/logs/phase09-dashboard.html" >/dev/null
grep -F 'id="heatmap"' "$PROJECT_ROOT/artifacts/logs/phase09-dashboard.html" >/dev/null
echo "dashboard=PASS status=200 count_queue_heatmap=present"

curl --fail --silent http://127.0.0.1:39110/api/v1/state \
  -o "$PROJECT_ROOT/artifacts/logs/phase09-state.json"
curl --fail --silent http://127.0.0.1:39110/api/v1/config \
  -o "$PROJECT_ROOT/artifacts/logs/phase09-config.json"

if docker inspect ntc-vss-phase09-behavior-analytics \
  --format '{{range .Mounts}}{{println .Source}}{{end}}' \
  | grep -F "$PROJECT_ROOT/runtime/raw-video" >/dev/null; then
  echo "ERROR: Phase 09 must not mount raw video storage." >&2
  exit 1
fi
echo "plane_isolation=PASS metadata_topic_only"

if docker logs ntc-vss-phase09-behavior-analytics 2>&1 \
  | grep -Eiq 'rtsp://[^/@[:space:]]+:[^/@[:space:]]+@'; then
  echo "ERROR: RTSP credential found in Phase 09 logs." >&2
  exit 1
fi
echo "secret_log_scan=PASS"
echo "completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
