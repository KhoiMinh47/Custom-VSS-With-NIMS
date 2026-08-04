#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/rtcv-lib.sh"
duration="${SOAK_DURATION_SECONDS:-7200}"
interval="${SOAK_INTERVAL_SECONDS:-30}"
if (( duration < 7200 )) && [[ "${ALLOW_SHORT_SOAK:-false}" != "true" ]]; then
  echo "ERROR: Phase 07 evidence requires a soak of at least 7200 seconds." >&2
  exit 2
fi

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
directory="$PROJECT_ROOT/artifacts/benchmarks/rtcv-1-camera/soak-$stamp"
samples="$directory/samples.jsonl"
summary="$directory/summary.json"
mkdir -p "$directory"

"$PROJECT_ROOT/scripts/healthcheck-rtcv.sh"
start_epoch="$(date +%s)"
end_epoch=$((start_epoch + duration))
failures=0
samples_count=0

while (( $(date +%s) < end_epoch )); do
  if ! "$PROJECT_ROOT/.venv/bin/python" - "$samples" <<'PY'
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from urllib.request import urlopen

def fetch(url):
    with urlopen(url, timeout=8) as response:
        return json.load(response)

state = fetch("http://127.0.0.1:39080/debug/state")
vendor = fetch("http://127.0.0.1:39000/api/v1/metrics")
streams = vendor.get("metrics-info", {}).get("stream-stats", [])
if len(streams) != 1 or streams[0].get("sensor_id") != "cam-01":
    raise RuntimeError("vendor metrics must contain only cam-01")
if not state["ready"]:
    raise RuntimeError("metadata consumer is not ready")
if state["decode_errors"] or state["elasticsearch_errors"] or state["publish_errors"]:
    raise RuntimeError("metadata service reported a processing error")
if os.path.exists(sys.argv[1]) and os.path.getsize(sys.argv[1]) > 0:
    with open(sys.argv[1], encoding="utf-8") as source:
        previous = json.loads(source.readlines()[-1])
    previous_streams = previous["vendor_metrics"]["stream-stats"]
    if streams[0]["frame_number"] <= previous_streams[0]["frame_number"]:
        raise RuntimeError("DeepStream frame counter did not advance")
gpu = subprocess.check_output(
    [
        "nvidia-smi",
        "--query-gpu=memory.used,memory.total,utilization.gpu,utilization.memory,"
        "temperature.gpu,power.draw",
        "--format=csv,noheader,nounits",
    ],
    text=True,
).strip().split(",")
record = {
    "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "schema_version": "1.0.0",
    "store_id": "store-001",
    "camera_id": "cam-01",
    "model_version": "1.0.2",
    "frames": state["frames"],
    "objects": state["objects"],
    "tracked_objects": state["tracked_objects"],
    "last_message_age_seconds": state["last_message_age_seconds"],
    "decode_errors": state["decode_errors"],
    "elasticsearch_errors": state["elasticsearch_errors"],
    "publish_errors": state["publish_errors"],
    "gpu_memory_used_mib": float(gpu[0]),
    "gpu_memory_total_mib": float(gpu[1]),
    "gpu_util_percent": float(gpu[2]),
    "gpu_memory_util_percent": float(gpu[3]),
    "gpu_temperature_c": float(gpu[4]),
    "gpu_power_w": float(gpu[5]),
    "vendor_metrics": vendor.get("metrics-info", {}),
}
with open(sys.argv[1], "a", encoding="utf-8") as output:
    output.write(json.dumps(record, separators=(",", ":")) + "\n")
PY
  then
    failures=$((failures + 1))
    echo "ERROR: soak continuity sample failed; stopping early." >&2
    break
  fi
  samples_count=$((samples_count + 1))
  sleep "$interval"
done

end_actual="$(date +%s)"
"$PROJECT_ROOT/.venv/bin/python" - "$samples" "$summary" \
  "$start_epoch" "$end_actual" "$samples_count" "$failures" <<'PY'
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

samples_path, summary_path = Path(sys.argv[1]), Path(sys.argv[2])
start, end, count, failures = map(int, sys.argv[3:])
records = [
    json.loads(line)
    for line in samples_path.read_text(encoding="utf-8").splitlines()
    if line.strip()
]
if not records:
    raise SystemExit("ERROR: no successful soak sample")
summary = {
    "schema_version": "1.0.0",
    "result": "PASS" if failures == 0 else "PARTIAL",
    "store_id": "store-001",
    "camera_id": "cam-01",
    "model_id": "rtdetr-warehouse-2d",
    "model_version": "1.0.2",
    "tracker": "NvDCF",
    "started_at": datetime.fromtimestamp(start, tz=UTC).isoformat().replace("+00:00", "Z"),
    "ended_at": datetime.fromtimestamp(end, tz=UTC).isoformat().replace("+00:00", "Z"),
    "duration_seconds": end - start,
    "sample_attempts": count,
    "sample_failures": failures,
    "frames_delta": records[-1]["frames"] - records[0]["frames"],
    "tracked_objects_delta": records[-1]["tracked_objects"] - records[0]["tracked_objects"],
    "max_gpu_memory_used_mib": max(item["gpu_memory_used_mib"] for item in records),
    "max_gpu_util_percent": max(item["gpu_util_percent"] for item in records),
    "max_last_message_age_seconds": max(
        item["last_message_age_seconds"] for item in records
    ),
    "decode_errors_delta": records[-1]["decode_errors"] - records[0]["decode_errors"],
    "elasticsearch_errors_delta": (
        records[-1]["elasticsearch_errors"] - records[0]["elasticsearch_errors"]
    ),
    "publish_errors_delta": (
        records[-1]["publish_errors"] - records[0]["publish_errors"]
    ),
}
summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, indent=2))
if summary["duration_seconds"] < 7200 and failures == 0:
    print("NOTE: short soak was explicitly enabled; it is not Phase 07 gate evidence.")
PY

if (( failures > 0 )); then
  echo "ERROR: soak had $failures failed sample(s)." >&2
  exit 1
fi
"$PROJECT_ROOT/scripts/test-rtcv.sh"
