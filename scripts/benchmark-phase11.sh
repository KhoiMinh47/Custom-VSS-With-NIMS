#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
benchmark_dir="$PROJECT_ROOT/artifacts/benchmarks/rt-vlm-alert"
log_file="$PROJECT_ROOT/artifacts/logs/phase11-direct-benchmark.txt"
mkdir -p "$benchmark_dir" "$PROJECT_ROOT/artifacts/logs"
exec > >(tee "$log_file") 2>&1

cleanup() {
  "$PROJECT_ROOT/scripts/stop-phase11-direct.sh" || true
}
trap cleanup EXIT

echo "phase=11"
echo "benchmark_started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
"$PROJECT_ROOT/scripts/start-phase11-direct.sh"

"$PROJECT_ROOT/.venv/bin/python" - "$benchmark_dir" <<'PY'
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

target = Path(sys.argv[1])

def get_json(url: str, payload: dict | None = None) -> dict:
    request = Request(
        url,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    with urlopen(request, timeout=10) as response:
        return json.load(response)

before_alerts = get_json("http://127.0.0.1:39210/api/v1/alerts?size=500")["alerts"]
before_ids = {item["direct_alert_id"] for item in before_alerts}
samples = []
deadline = time.monotonic() + 900
successful = []
while time.monotonic() < deadline:
    output = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=timestamp,memory.used,memory.total,utilization.gpu,power.draw",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    fields = [field.strip() for field in output.split(",")]
    samples.append(
        {
            "timestamp": fields[0],
            "memory_used_mib": int(fields[1]),
            "memory_total_mib": int(fields[2]),
            "gpu_utilization_percent": int(fields[3]),
            "power_watts": float(fields[4]),
        }
    )
    current = get_json("http://127.0.0.1:39210/api/v1/alerts?size=500")["alerts"]
    successful = [
        item
        for item in current
        if item["direct_alert_id"] not in before_ids
        and item.get("raw_response_excerpt")
        and int(item.get("vlm_latency_ms", 0)) > 0
        and 0 < int(item.get("frame_count", 0)) <= 5
    ]
    if len(successful) >= 2:
        break
    time.sleep(5)
else:
    raise SystemExit("ERROR: two actual direct RT-VLM chunk results were not persisted")

comparison = get_json("http://127.0.0.1:39210/api/v1/comparison")
state = get_json("http://127.0.0.1:39210/api/v1/state")
stream = get_json("http://127.0.0.1:39200/v1/stream/get-stream-info")
new_alerts = successful
report = {
    "schema_version": "1.0.0",
    "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "store_id": "store-001",
    "camera_id": "cam-01",
    "use_case_id": "person-presence-direct-v1",
    "chunk_duration_seconds": 8,
    "fixed_frames_per_chunk": 5,
    "actual_direct_results": len(new_alerts),
    "verdicts": {
        verdict: sum(item["verdict"] == verdict for item in new_alerts)
        for verdict in ("confirmed", "rejected", "uncertain")
    },
    "latency_ms": [item["latency_ms"] for item in new_alerts],
    "frame_counts": [item["frame_count"] for item in new_alerts],
    "input_tokens": sum(item["input_tokens"] for item in new_alerts),
    "output_tokens": sum(item["output_tokens"] for item in new_alerts),
    "gpu": {
        "samples": len(samples),
        "peak_memory_used_mib": max(item["memory_used_mib"] for item in samples),
        "peak_utilization_percent": max(
            item["gpu_utilization_percent"] for item in samples
        ),
        "peak_power_watts": max(item["power_watts"] for item in samples),
    },
    "comparison": comparison,
}
(target / "benchmark.json").write_text(json.dumps(report, indent=2) + "\n")
(target / "gpu-samples.json").write_text(json.dumps(samples, indent=2) + "\n")
(target / "direct-alerts.json").write_text(json.dumps(new_alerts, indent=2) + "\n")
(target / "collector-state.json").write_text(json.dumps(state, indent=2) + "\n")
(target / "stream-state.json").write_text(json.dumps(stream, indent=2) + "\n")
print(
    f'direct_results={len(new_alerts)} '
    f'peak_gpu_memory_mib={report["gpu"]["peak_memory_used_mib"]}'
)
PY

docker logs ntc-vss-phase11-rt-vlm 2>&1 \
  | sed -E 's#(rtsp://)[^/@[:space:]]+:[^/@[:space:]]+@#\1[REDACTED]@#g' \
  > "$PROJECT_ROOT/artifacts/logs/phase11-rt-vlm.log"
docker logs ntc-vss-retail-poc-gpu-poc-cosmos3-1 2>&1 \
  | grep -E \
    'Skipping download, using cached copy|server is up and ready|POST /v1/chat/completions' \
  > "$PROJECT_ROOT/artifacts/logs/phase11-cosmos3-cache-and-inference.txt"

echo "benchmark_completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cleanup
trap - EXIT
"$PROJECT_ROOT/scripts/healthcheck-rtcv.sh"
"$PROJECT_ROOT/scripts/healthcheck-video-management.sh"
echo "phase11_direct_benchmark=PASS"
