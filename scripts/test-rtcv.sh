#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/rtcv-lib.sh"
evidence="$PROJECT_ROOT/artifacts/logs/phase07-rtcv-smoke.txt"
mkdir -p "$(dirname "$evidence")" "$PROJECT_ROOT/artifacts/benchmarks/rtcv-1-camera"

exec > >(tee "$evidence") 2>&1
echo "phase=07"
echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
"$PROJECT_ROOT/scripts/healthcheck-rtcv.sh"

"$PROJECT_ROOT/.venv/bin/python" - "$PROJECT_ROOT" <<'PY'
import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen

root = Path(sys.argv[1])
with urlopen(
    "http://127.0.0.1:39000/api/v1/stream/get-stream-info", timeout=10
) as response:
    stream_info = json.load(response)
stream_payload = stream_info.get("stream-info", {})
for item in stream_payload.get("stream-info", stream_payload.get("stream-list", [])):
    item["camera_url"] = "rtsp://[runtime-selected-ai-substream]"
(root / "artifacts/logs/phase07-rtcv-stream-info.json").write_text(
    json.dumps(stream_info, indent=2) + "\n", encoding="utf-8"
)

with urlopen("http://127.0.0.1:39000/api/v1/metrics", timeout=10) as response:
    vendor_metrics = json.load(response)
(root / "artifacts/benchmarks/rtcv-1-camera/vendor-metrics.json").write_text(
    json.dumps(vendor_metrics, indent=2) + "\n", encoding="utf-8"
)

query = {
    "size": 20,
    "sort": [{"@timestamp": {"order": "desc"}}],
    "query": {
        "bool": {
            "filter": [
                {"term": {"store_id": "store-001"}},
                {"term": {"camera_id": "cam-01"}},
                {"term": {"event_type": "rt_cv.frame"}},
                {"term": {"model_version": "1.0.2"}},
            ]
        }
    },
}
request = Request(
    "http://127.0.0.1:9200/mdx-raw/_search",
    data=json.dumps(query).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urlopen(request, timeout=15) as response:
    search = json.load(response)
hits = search.get("hits", {}).get("hits", [])
if not hits:
    raise SystemExit("ERROR: no stable RT-CV frame contract found in Elasticsearch")
sources = [item["_source"] for item in hits]
if not all(
    item.get("schema_version") == "1.0.0"
    and item.get("store_id") == "store-001"
    and item.get("camera_id") == "cam-01"
    and item.get("model_id") == "rtdetr-warehouse-2d"
    and item.get("model_version") == "1.0.2"
    and str(item.get("@timestamp", "")).endswith("Z")
    for item in sources
):
    raise SystemExit("ERROR: indexed metadata contract is incomplete")
tracked = [
    obj
    for item in sources
    for obj in item.get("payload", {}).get("objects", [])
    if obj.get("track_id")
]
if not tracked:
    raise SystemExit("ERROR: no NvDCF track ID observed in the latest metadata")
sample = {"_index": hits[0]["_index"], "_source": hits[0]["_source"]}
(root / "artifacts/logs/phase07-elasticsearch-sample.json").write_text(
    json.dumps(sample, indent=2) + "\n", encoding="utf-8"
)
print(f"elasticsearch_contract=PASS hits={len(hits)} tracked_objects={len(tracked)}")

line_query = {
    "size": 1,
    "sort": [{"@timestamp": {"order": "desc"}}],
    "query": {
        "bool": {
            "filter": [
                {"term": {"store_id": "store-001"}},
                {"term": {"camera_id": "cam-01"}},
                {"term": {"event_type": "line_crossing.smoke"}},
                {"term": {"model_version": "1.0.2"}},
            ]
        }
    },
}
line_request = Request(
    "http://127.0.0.1:9200/mdx-raw/_search",
    data=json.dumps(line_query).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urlopen(line_request, timeout=15) as response:
    line_search = json.load(response)
line_hits = line_search.get("hits", {}).get("hits", [])
if not line_hits or not line_hits[0]["_source"].get("payload", {}).get("track_id"):
    raise SystemExit("ERROR: no tracked line-crossing smoke event found")
(root / "artifacts/logs/phase07-line-crossing-sample.json").write_text(
    json.dumps(line_hits[0], indent=2) + "\n", encoding="utf-8"
)
print("line_crossing_smoke=PASS hits=1")
PY

engine="$RTCV_ENGINE_DIR/rtdetr_warehouse_v1.0.2.fp16.onnx_b1_gpu0_fp16.engine"
if [[ ! -s "$engine" ]]; then
  echo "ERROR: project-local RT-DETR batch-1 TensorRT engine is missing." >&2
  exit 1
fi
sha256sum "$engine" \
  > "$PROJECT_ROOT/artifacts/manifests/phase07-rtdetr-engine-sha256.txt"
echo "tensorrt_engine=PASS"

if docker ps --format '{{.Names}} {{.Image}}' \
  | grep -E 'nemotron|cosmos3|rt-embed|rt-vlm' \
  | grep -v 'ntc-vss-phase07' \
  | grep -v '^ntc-vss-phase11-rt-vlm-results ' >/dev/null; then
  echo "ERROR: out-of-scope GPU service is running." >&2
  exit 1
fi
echo "gpu_scope=PASS rtcv_only"

if docker inspect ntc-vss-phase07-rtcv ntc-vss-phase07-metadata \
  --format '{{range .Mounts}}{{println .Source}}{{end}}' \
  | grep -F "$PROJECT_ROOT/runtime/raw-video" >/dev/null; then
  echo "ERROR: the RT-CV/metadata plane must not mount Phase 06 raw storage." >&2
  exit 1
fi
echo "plane_isolation=PASS no_raw_storage_mount"

overlay="$PROJECT_ROOT/artifacts/logs/phase07-debug-overlay.html"
curl --fail --silent --show-error \
  http://127.0.0.1:39080/debug/overlay -o "$overlay"
if ! grep -F 'cam-01 metadata overlay' "$overlay" >/dev/null \
  || ! grep -F '<svg viewBox=' "$overlay" >/dev/null; then
  echo "ERROR: the cam-01 metadata debug overlay did not render." >&2
  exit 1
fi
echo "debug_overlay=PASS cam01_context_rendered"

if docker logs ntc-vss-phase07-rtcv 2>&1 \
  | grep -Eiq 'rtsp://[^/@[:space:]]+:[^/@[:space:]]+@'; then
  echo "ERROR: credential-bearing RTSP URI found in RT-CV logs." >&2
  exit 1
fi
if docker logs ntc-vss-phase07-rtsp-relay 2>&1 \
  | grep -Eiq 'rtsp://[^/@[:space:]]+:[^/@[:space:]]+@'; then
  echo "ERROR: credential-bearing RTSP URI found in relay logs." >&2
  exit 1
fi
echo "secret_log_scan=PASS"

nvidia-smi \
  --query-gpu=timestamp,name,memory.used,memory.total,utilization.gpu,utilization.memory,temperature.gpu,power.draw \
  --format=csv,noheader \
  | tee "$PROJECT_ROOT/artifacts/benchmarks/rtcv-1-camera/gpu-smoke.csv"
echo "completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
