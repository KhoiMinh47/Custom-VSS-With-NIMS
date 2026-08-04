from __future__ import annotations

import html
import json
import os
import signal
import sys
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml
from google.protobuf.json_format import MessageToDict
from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import KafkaError

from contracts import (
    CAMERA_ID,
    SCHEMA_VERSION,
    frame_document,
    line_crossing_document,
    line_side,
    normalize_bbox,
    point_in_polygon,
    utc_iso,
)

PROTO_DIR = Path(os.environ.get("NVIDIA_PROTO_DIR", "/opt/nvidia-protos"))
sys.path.insert(0, str(PROTO_DIR))
import schema_pb2  # type: ignore[import-not-found]  # noqa: E402


def log(level: str, event: str, **fields: object) -> None:
    print(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "level": level,
                "service": "phase07-rtcv-metadata",
                "event": event,
                "camera_id": CAMERA_ID,
                **fields,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


class State:
    def __init__(self, analytics: dict[str, Any]) -> None:
        self.lock = threading.Lock()
        self.started = time.monotonic()
        self.ready = False
        self.frames = 0
        self.objects = 0
        self.tracked_objects = 0
        self.decode_errors = 0
        self.elasticsearch_errors = 0
        self.publish_errors = 0
        self.line_crossings = 0
        self.last_message_monotonic = 0.0
        self.last_frame: dict[str, Any] = {}
        self.track_sides: dict[str, float] = {}
        self.analytics = analytics

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            age = (
                time.monotonic() - self.last_message_monotonic
                if self.last_message_monotonic
                else -1
            )
            return {
                "ready": self.ready,
                "frames": self.frames,
                "objects": self.objects,
                "tracked_objects": self.tracked_objects,
                "decode_errors": self.decode_errors,
                "elasticsearch_errors": self.elasticsearch_errors,
                "publish_errors": self.publish_errors,
                "line_crossings": self.line_crossings,
                "last_message_age_seconds": round(age, 3) if age >= 0 else -1,
                "uptime_seconds": round(time.monotonic() - self.started, 3),
                "last_frame": self.last_frame,
            }


def es_put(base_url: str, document_id: str, document: dict[str, Any]) -> None:
    request = Request(
        f"{base_url.rstrip('/')}/mdx-raw/_doc/{document_id}",
        data=json.dumps(document, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    with urlopen(request, timeout=10) as response:
        if response.status not in {200, 201}:
            raise RuntimeError(f"Elasticsearch returned HTTP {response.status}")


def timestamp_from_frame(frame: dict[str, Any]) -> str:
    value = frame.get("timestamp", {})
    if isinstance(value, str):
        if value.endswith("Z"):
            return value
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC).isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        )
    seconds = int(value.get("seconds", 0))
    nanos = int(value.get("nanos", 0))
    if seconds <= 0:
        return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return utc_iso(seconds, nanos)


def clean_objects(frame: dict[str, Any]) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for value in frame.get("objects", []):
        track_id = str(value.get("id", ""))
        object_type = str(value.get("type", ""))
        confidence = min(1.0, max(0.0, float(value.get("confidence", 0.0))))
        objects.append(
            {
                "track_id": track_id,
                "type": object_type,
                "confidence": confidence,
                "bbox": normalize_bbox(value.get("bbox", {})),
            }
        )
    return objects


def maybe_line_crossings(
    state: State,
    frame_id: str,
    timestamp: str,
    objects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    config = state.analytics["line_crossing"]
    roi = state.analytics["roi"]["polygon"]
    start = tuple(float(item) for item in config["start"])
    end = tuple(float(item) for item in config["end"])
    deadband = float(config.get("deadband", 0.02))
    allowed = {str(item).lower() for item in config.get("object_types", ["Person"])}
    events: list[dict[str, Any]] = []
    for detected in objects:
        track_id = detected["track_id"]
        if not track_id or detected["type"].lower() not in allowed:
            continue
        bbox = detected["bbox"]
        point = ((bbox["left"] + bbox["right"]) / 2, bbox["bottom"])
        if not point_in_polygon(point, roi):
            continue
        side = line_side(point, start, end)
        previous = state.track_sides.get(track_id)
        state.track_sides[track_id] = side
        if previous is None or abs(previous) <= deadband or abs(side) <= deadband:
            continue
        if (previous < 0 < side) or (side < 0 < previous):
            direction = "negative_to_positive" if previous < side else "positive_to_negative"
            events.append(
                line_crossing_document(
                    frame_id,
                    timestamp,
                    track_id,
                    str(config["id"]),
                    direction,
                    bbox,
                )
            )
    return events


class Handler(BaseHTTPRequestHandler):
    state: State

    def _write_json(self, status: int, body: dict[str, Any]) -> None:
        content = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:  # noqa: N802
        snapshot = self.state.snapshot()
        if self.path == "/health/live":
            self._write_json(200, {"status": "ok", "schema_version": SCHEMA_VERSION})
        elif self.path == "/health/ready":
            ready = bool(snapshot["ready"])
            self._write_json(
                200 if ready else 503,
                {
                    "status": "ready" if ready else "not_ready",
                    "schema_version": SCHEMA_VERSION,
                    "camera_id": CAMERA_ID,
                    "last_message_age_seconds": snapshot["last_message_age_seconds"],
                },
            )
        elif self.path == "/debug/state":
            self._write_json(200, snapshot)
        elif self.path == "/metrics":
            self._write_metrics(snapshot)
        elif self.path == "/debug/overlay":
            self._write_overlay(snapshot)
        else:
            self.send_error(404)

    def _write_metrics(self, snapshot: dict[str, Any]) -> None:
        lines = [
            "# HELP rtcv_frames_total Decoded and indexed RT-CV frames.",
            "# TYPE rtcv_frames_total counter",
            f'rtcv_frames_total{{camera_id="{CAMERA_ID}"}} {snapshot["frames"]}',
            "# HELP rtcv_objects_total RT-CV objects observed.",
            "# TYPE rtcv_objects_total counter",
            f'rtcv_objects_total{{camera_id="{CAMERA_ID}"}} {snapshot["objects"]}',
            "# HELP rtcv_tracked_objects_total Objects carrying a stable track ID.",
            "# TYPE rtcv_tracked_objects_total counter",
            f'rtcv_tracked_objects_total{{camera_id="{CAMERA_ID}"}} '
            f'{snapshot["tracked_objects"]}',
            "# HELP rtcv_line_crossings_total Smoke line-crossing events.",
            "# TYPE rtcv_line_crossings_total counter",
            f'rtcv_line_crossings_total{{camera_id="{CAMERA_ID}"}} '
            f'{snapshot["line_crossings"]}',
            "# HELP rtcv_last_message_age_seconds Age of the last broker frame.",
            "# TYPE rtcv_last_message_age_seconds gauge",
            f'rtcv_last_message_age_seconds{{camera_id="{CAMERA_ID}"}} '
            f'{snapshot["last_message_age_seconds"]}',
            "# HELP rtcv_decode_errors_total Protobuf decode errors.",
            "# TYPE rtcv_decode_errors_total counter",
            f'rtcv_decode_errors_total{{camera_id="{CAMERA_ID}"}} '
            f'{snapshot["decode_errors"]}',
            "# HELP rtcv_elasticsearch_errors_total Elasticsearch write errors.",
            "# TYPE rtcv_elasticsearch_errors_total counter",
            f'rtcv_elasticsearch_errors_total{{camera_id="{CAMERA_ID}"}} '
            f'{snapshot["elasticsearch_errors"]}',
            "# HELP rtcv_publish_errors_total Kafka publish or commit errors.",
            "# TYPE rtcv_publish_errors_total counter",
            f'rtcv_publish_errors_total{{camera_id="{CAMERA_ID}"}} '
            f'{snapshot["publish_errors"]}',
        ]
        content = ("\n".join(lines) + "\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _write_overlay(self, snapshot: dict[str, Any]) -> None:
        frame = snapshot.get("last_frame") or {}
        objects = frame.get("objects", [])
        shapes = []
        for detected in objects:
            bbox = detected["bbox"]
            x = bbox["left"] * 1000
            y = bbox["top"] * 562.5
            width = max(1, (bbox["right"] - bbox["left"]) * 1000)
            height = max(1, (bbox["bottom"] - bbox["top"]) * 562.5)
            label = html.escape(
                f'{detected["type"]} #{detected["track_id"]} '
                f'{detected["confidence"]:.2f}'
            )
            shapes.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" '
                f'height="{height:.1f}" class="box"/>'
                f'<text x="{x:.1f}" y="{max(14, y - 4):.1f}">{label}</text>'
            )
        body = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Phase 07 RT-CV overlay</title>
<style>
body{{background:#111;color:#eee;font-family:system-ui;margin:24px}}
svg{{background:#222;border:1px solid #555;max-width:100%;height:auto}}
.box{{fill:none;stroke:#76ff03;stroke-width:3}}text{{fill:#fff;font-size:14px}}
.line{{stroke:#ffca28;stroke-width:3;stroke-dasharray:8 6}}
</style></head><body>
<h1>cam-01 metadata overlay</h1>
<p>RT-DETR Warehouse 2D v1.0.2 FP16 · NvDCF · UTC:
{html.escape(str(frame.get("timestamp", "waiting")))}</p>
<svg viewBox="0 0 1000 562.5" aria-label="normalized metadata overlay">
<line x1="500" y1="28" x2="500" y2="534" class="line"/>
{''.join(shapes)}
</svg>
<p>Frames: {snapshot["frames"]} · Objects: {snapshot["objects"]} ·
Tracked: {snapshot["tracked_objects"]}</p>
</body></html>"""
        content = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def consume_session(state: State, stop: threading.Event) -> None:
    kafka_bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    es_url = os.environ.get("ELASTICSEARCH_URL", "http://elasticsearch:9200")
    consumer = KafkaConsumer(
        "mdx-raw",
        bootstrap_servers=kafka_bootstrap,
        group_id=os.environ.get("KAFKA_CONSUMER_GROUP", "phase07-rtcv-indexer-v1"),
        auto_offset_reset="latest",
        enable_auto_commit=False,
        consumer_timeout_ms=1000,
        max_poll_records=20,
    )
    producer = KafkaProducer(
        bootstrap_servers=kafka_bootstrap,
        value_serializer=lambda value: json.dumps(
            value, separators=(",", ":")
        ).encode(),
    )
    log("info", "broker_connected", topic="mdx-raw")
    with state.lock:
        state.ready = True
    while not stop.is_set():
        for record in consumer:
            if stop.is_set():
                break
            message = schema_pb2.Frame()
            try:
                message.ParseFromString(record.value)
                frame = MessageToDict(message, preserving_proto_field_name=True)
                if str(frame.get("sensorId", "")) != CAMERA_ID:
                    log(
                        "warning",
                        "unexpected_camera_rejected",
                        sensor_id=str(frame.get("sensorId", "")),
                    )
                    consumer.commit()
                    continue
                timestamp = timestamp_from_frame(frame)
                objects = clean_objects(frame)
                document = frame_document(frame, timestamp, objects)
                events = maybe_line_crossings(
                    state, document["payload"]["frame_id"], timestamp, objects
                )
                es_put(es_url, document["correlation_id"], document)
                producer.send("vss.rt-cv.frames", document).get(timeout=10)
                for event in events:
                    es_put(es_url, event["correlation_id"], event)
                    producer.send("vss.behavior.events", event).get(timeout=10)
                consumer.commit()
            except (HTTPError, URLError, RuntimeError) as error:
                with state.lock:
                    state.elasticsearch_errors += 1
                log(
                    "error",
                    "elasticsearch_write_failed",
                    error_type=type(error).__name__,
                )
                continue
            except (KafkaError, TimeoutError) as error:
                with state.lock:
                    state.publish_errors += 1
                log("error", "broker_write_failed", error_type=type(error).__name__)
                consumer.close()
                producer.close(timeout=10)
                raise
            except Exception as error:
                with state.lock:
                    state.decode_errors += 1
                log("error", "frame_decode_failed", error_type=type(error).__name__)
                consumer.commit()
                continue
            with state.lock:
                state.frames += 1
                state.objects += len(objects)
                state.tracked_objects += sum(bool(item["track_id"]) for item in objects)
                state.line_crossings += len(events)
                state.last_message_monotonic = time.monotonic()
                state.last_frame = {
                    "frame_id": document["payload"]["frame_id"],
                    "timestamp": timestamp,
                    "objects": objects,
                }
                frame_count = state.frames
            if events:
                log("info", "line_crossing_emitted", count=len(events))
            if frame_count == 1 or frame_count % 300 == 0:
                log("info", "frame_progress", frames=frame_count)
        time.sleep(0.1)
    producer.flush(timeout=10)
    producer.close()
    consumer.close()
    log("info", "consumer_stopped")


def consume(state: State, stop: threading.Event) -> None:
    """Keep the metadata plane alive across Kafka restarts/outages."""
    retry_seconds = max(1.0, float(os.environ.get("KAFKA_RECONNECT_SECONDS", "5")))
    while not stop.is_set():
        try:
            consume_session(state, stop)
            return
        except (KafkaError, OSError, TimeoutError) as error:
            with state.lock:
                state.ready = False
            log(
                "warning",
                "broker_reconnect_scheduled",
                error_type=type(error).__name__,
                retry_seconds=retry_seconds,
            )
            stop.wait(retry_seconds)


def main() -> int:
    analytics_path = Path(os.environ.get("ANALYTICS_CONFIG", "/config/cam-01.yaml"))
    analytics = yaml.safe_load(analytics_path.read_text(encoding="utf-8"))
    if analytics.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError("unsupported analytics schema version")
    if analytics.get("camera_id") != CAMERA_ID:
        raise RuntimeError("Phase 07 is restricted to cam-01")
    state = State(analytics)
    Handler.state = state
    stop = threading.Event()
    worker = threading.Thread(target=consume, args=(state, stop), daemon=True)
    worker.start()
    server = ThreadingHTTPServer(
        ("0.0.0.0", int(os.environ.get("HTTP_PORT", "8080"))), Handler
    )

    def shutdown(_signum: int, _frame: object) -> None:
        log("info", "shutdown_requested")
        stop.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    log("info", "service_started", schema_version=SCHEMA_VERSION)
    try:
        server.serve_forever()
    finally:
        stop.set()
        worker.join(timeout=15)
        server.server_close()
        log("info", "service_stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
