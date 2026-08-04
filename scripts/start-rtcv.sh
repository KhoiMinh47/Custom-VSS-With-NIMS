#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/rtcv-lib.sh"

"$PROJECT_ROOT/scripts/healthcheck-infra.sh"
"$PROJECT_ROOT/scripts/healthcheck-video-management.sh"
rtcv_require_admission

actual_digest="$(
  docker image inspect "$RTCV_IMAGE" \
    --format '{{index .RepoDigests 0}}' 2>/dev/null || true
)"
if [[ "$actual_digest" != *"sha256:1a8b9879686f21cb6b9589d6139b5ac2eb960f1520aa3b4bb5f079d05fee9458" ]]; then
  echo "ERROR: the pinned VSS 3.2.1 RT-CV image is unavailable." >&2
  exit 1
fi

model="$PROJECT_ROOT/models/rtdetr/rtdetr_warehouse_v1.0.2.fp16.onnx"
if [[ "$(sha256sum "$model" | awk '{print $1}')" != \
  "0a22264542514149bead6e8582499d9758d51e3fde2892d9d2cc378a60426267" ]]; then
  echo "ERROR: the approved RT-DETR ONNX hash does not match." >&2
  exit 1
fi

mkdir -p "$RTCV_ENGINE_DIR" "$PROJECT_ROOT/artifacts/benchmarks/rtcv-1-camera"
chmod 700 "$RTCV_ENGINE_DIR"
cached_onnx="$RTCV_ENGINE_DIR/rtdetr_warehouse_v1.0.2.fp16.onnx"
if [[ ! -f "$cached_onnx" ]]; then
  cp --reflink=auto --preserve=mode,timestamps "$model" "$cached_onnx"
fi
if [[ "$(sha256sum "$cached_onnx" | awk '{print $1}')" != \
  "0a22264542514149bead6e8582499d9758d51e3fde2892d9d2cc378a60426267" ]]; then
  echo "ERROR: project-local TensorRT build input hash does not match." >&2
  exit 1
fi

"$PROJECT_ROOT/scripts/camera-api.sh" lease
rtcv_compose config --quiet

docker exec ntc-vss-retail-poc-kafka-1 \
  /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server kafka:9092 \
  --create --if-not-exists \
  --topic mdx-raw --partitions 3 --replication-factor 1 >/dev/null
docker exec ntc-vss-retail-poc-kafka-1 \
  /opt/kafka/bin/kafka-configs.sh \
  --bootstrap-server kafka:9092 \
  --entity-type topics --entity-name mdx-raw \
  --alter --add-config retention.ms=86400000 >/dev/null

rtcv_compose up -d

deadline=$((SECONDS + 1200))
until curl --fail --silent --max-time 5 \
  http://127.0.0.1:39000/api/v1/ready >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    rtcv_compose ps
    echo "ERROR: RT-CV readiness deadline exceeded." >&2
    exit 1
  fi
  sleep 5
done

"$PROJECT_ROOT/.venv/bin/python" - <<'PY'
import json
from datetime import UTC, datetime
from urllib.request import Request, urlopen

payload = {
    "key": "sensor",
    "value": {
        "camera_id": "cam-01",
        "camera_name": "cam-01",
        "camera_url": "rtsp://rtsp-relay:39554/Streaming/Channels/102",
        "change": "camera_add",
        "metadata": {
            "resolution": "1280 x720",
            "codec": "h264",
            "framerate": 25,
            "store_id": "store-001",
            "schema_version": "1.0.0",
            "model_version": "1.0.2",
            "source_role": "ai_substream",
            "logical_channel": "102",
            "upstream_channel": "102",
            "fallback_upstream_channel": "101",
            "source_selection": "physical_102_preferred",
        },
    },
    "headers": {
        "source": "ntc-phase07-secure-relay",
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    },
}
request = Request(
    "http://127.0.0.1:39000/api/v1/stream/add",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urlopen(request, timeout=30) as response:
        if response.status not in {200, 201}:
            raise RuntimeError(f"stream add returned HTTP {response.status}")
except Exception as error:
    with urlopen(
        "http://127.0.0.1:39000/api/v1/stream/get-stream-info", timeout=10
    ) as response:
        current = json.load(response)
    stream_info = current.get("stream-info", {})
    streams = stream_info.get("stream-info", stream_info.get("stream-list", []))
    if len(streams) != 1 or streams[0].get("camera_id") != "cam-01":
        raise RuntimeError("cam-01 stream registration failed") from error
print("rtcv_source=cam-01:physical-substream-102-via-secure-relay")
PY

deadline=$((SECONDS + 300))
until curl --fail --silent --max-time 5 \
  http://127.0.0.1:39080/health/ready >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    rtcv_compose ps
    echo "ERROR: metadata readiness deadline exceeded." >&2
    exit 1
  fi
  sleep 5
done

curl --fail --silent --show-error -X POST \
  http://127.0.0.1:9090/-/reload >/dev/null
"$PROJECT_ROOT/scripts/healthcheck-rtcv.sh"
