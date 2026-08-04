from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from google.protobuf.json_format import MessageToDict
from kafka import KafkaConsumer

PROTO_DIR = Path(os.environ.get("NVIDIA_PROTO_DIR", "/opt/nvidia-protos"))
import sys

sys.path.insert(0, str(PROTO_DIR))
import schema_pb2  # type: ignore[import-not-found]  # noqa: E402


SCHEMA_VERSION = "1.0.0"
STORE_ID = "store-001"
CAMERA_ID = "cam-01"
MODEL_ID = "rtdetr-warehouse-2d"
MODEL_VERSION = "1.0.2"
JOB_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_RUNTIME_SECONDS = 20 * 60


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _timestamp(frame: dict[str, Any]) -> datetime:
    value = frame.get("timestamp")
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC)
    if isinstance(value, dict):
        seconds = int(value.get("seconds", 0))
        nanos = int(value.get("nanos", 0))
        if seconds > 0:
            return datetime.fromtimestamp(seconds + nanos / 1_000_000_000, UTC)
    return datetime.now(UTC)


def _set_config_value(text: str, section: str, key: str, value: str) -> str:
    lines = text.splitlines()
    section_seen = False
    replaced = False
    output: list[str] = []
    for line in lines:
        if line.startswith("[") and line.endswith("]"):
            if section_seen and not replaced:
                output.append(f"{key}={value}")
                replaced = True
            section_seen = line == f"[{section}]"
        if section_seen and line.startswith(f"{key}="):
            output.append(f"{key}={value}")
            replaced = True
        else:
            output.append(line)
    if not replaced:
        if section_seen:
            output.append(f"{key}={value}")
        else:
            raise RuntimeError(f"RT-CV config section is missing: [{section}]")
    return "\n".join(output) + "\n"


def build_file_config(source: Path, target: Path, media_uri: str) -> None:
    text = source.read_text(encoding="utf-8")
    updates = {
        ("source-list", "num-source-bins"): "1",
        ("source-list", "list"): media_uri,
        ("source-list", "sensor-id-list"): CAMERA_ID,
        ("source-list", "sensor-name-list"): CAMERA_ID,
        ("source-list", "use-nvmultiurisrcbin"): "1",
        ("source-list", "file-loop"): "0",
        ("source-list", "max-batch-size"): "1",
        ("source-list", "low-latency-mode"): "0",
        ("source-attr-all", "file-loop"): "0",
        ("source-attr-all", "drop-on-latency"): "0",
        ("streammux", "live-source"): "0",
        ("streammux", "batch-size"): "1",
        ("streammux", "drop-pipeline-eos"): "0",
        ("primary-gie", "batch-size"): "1",
        ("primary-gie", "interval"): "0",
        ("sink0", "enable"): "0",
        ("sink1", "enable"): "1",
        ("sink2", "enable"): "0",
        ("tests", "file-loop"): "0",
    }
    for (section, key), value in updates.items():
        text = _set_config_value(text, section, key, value)
    target.write_text(text, encoding="utf-8")


def candidate_from_frame(job_id: str, frame: dict[str, Any]) -> dict[str, Any] | None:
    objects = [item for item in frame.get("objects", []) if isinstance(item, dict)]
    objects = [item for item in objects if float(item.get("confidence", 0.0)) >= 0.45]
    if not objects:
        return None
    moment = _timestamp(frame)
    start = moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    end = (moment + timedelta(seconds=1)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    frame_id = str(frame.get("id") or hashlib.sha256(json.dumps(frame, sort_keys=True).encode()).hexdigest())
    event_id = hashlib.sha256(
        f"{STORE_ID}|{CAMERA_ID}|{job_id}|rtcv.file.object_detected|{frame_id}".encode()
    ).hexdigest()
    return {
        "schema_version": SCHEMA_VERSION,
        "store_id": STORE_ID,
        "camera_id": CAMERA_ID,
        "event_id": event_id,
        "event_type": "rtcv.file.object_detected",
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "start_time": start,
        "end_time": end,
        "candidate": True,
        "evaluation": False,
        "confidence": max(float(item.get("confidence", 0.0)) for item in objects),
        "evidence": {
            "kind": "rtcv_file_batch_detection",
            "job_id": job_id,
            "frame_id": frame_id,
            "objects": objects[:50],
            "source": "pinned-vss-rt-cv-3.2.1",
        },
        "payload": {"job_id": job_id, "frame_id": frame_id, "objects": objects[:50]},
    }


class BatchRuntime:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.job_id: str | None = None
        self.status = "ready"
        self.candidate: dict[str, Any] | None = None
        self.frames = 0
        self.objects = 0
        self.error = ""
        self.started_at: str | None = None
        self.completed_at: str | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self.stop_requested = threading.Event()
        self.media_root = Path(os.environ.get("VLM_TEST_MEDIA_ROOT", "/runtime/vlm-test/staging"))
        self.config_source = Path(os.environ.get("RTCV_CONFIG_SOURCE", "/opt/ntc/rtcv-file-batch/mounted-configs/ds-main-config.txt"))
        self.config_target = Path(os.environ.get("RTCV_CONFIG_TARGET", "/opt/nvidia/deepstream/deepstream/sources/apps/sample_apps/metropolis_perception_app/configs"))
        self.ds_start = Path(os.environ.get("RTCV_DS_START", "/opt/nvidia/deepstream/deepstream/sources/apps/sample_apps/metropolis_perception_app/ds-start.sh"))
        self.app_config_root = self.config_target

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "schema_version": SCHEMA_VERSION,
                "store_id": STORE_ID,
                "camera_id": CAMERA_ID,
                "status": self.status,
                "job_id": self.job_id,
                "frames": self.frames,
                "objects": self.objects,
                "candidate": self.candidate,
                "error": self.error or None,
                "started_at": self.started_at,
                "completed_at": self.completed_at,
            }

    def _media_for_job(self, job_id: str) -> Path:
        if JOB_ID_PATTERN.fullmatch(job_id) is None:
            raise ValueError("job_id is invalid")
        matches = [self.media_root / f"{job_id}{extension}" for extension in (".mp4", ".mkv")]
        existing = [path for path in matches if path.is_file()]
        if len(existing) != 1:
            raise FileNotFoundError("staged VLM-test media was not found")
        return existing[0]

    def start(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            if self.status in {"starting", "running"}:
                raise RuntimeError("another RT-CV file job is running")
            media = self._media_for_job(job_id)
            self.job_id = job_id
            self.status = "starting"
            self.candidate = None
            self.frames = 0
            self.objects = 0
            self.error = ""
            self.started_at = utc_now()
            self.completed_at = None
            self.stop_requested.clear()
            worker = threading.Thread(target=self._run, args=(job_id, media), daemon=True, name=f"rtcv-file-{job_id[:12]}")
            worker.start()
            return self.snapshot()

    def _run(self, job_id: str, media: Path) -> None:
        consumer: KafkaConsumer | None = None
        process: subprocess.Popen[bytes] | None = None
        try:
            config_root = self.app_config_root
            config_root.mkdir(parents=True, exist_ok=True)
            for item in Path(os.environ.get("RTCV_CONFIG_SOURCE_ROOT", "/opt/ntc/rtcv-file-batch/mounted-configs")).iterdir():
                if item.is_file():
                    shutil.copy2(item, config_root / item.name)
            build_file_config(
                self.config_source,
                config_root / "ds-main-config.txt",
                f"file:///runtime/vlm-test/staging/{media.name}",
            )
            consumer = KafkaConsumer(
                "mdx-raw",
                bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
                group_id=f"phase15-vlm-test-{job_id[:24]}",
                auto_offset_reset="latest",
                enable_auto_commit=False,
            )
            deadline = time.monotonic() + 15
            while not consumer.assignment() and time.monotonic() < deadline:
                consumer.poll(timeout_ms=500)
            env = os.environ.copy()
            env.update({"DS_MODEL_FAMILY": "rtdetr-warehouse", "STREAM_TYPE": "kafka", "DS_MODE_FLAG": "1", "DS_MESSAGE_RATE": "1", "DS_SHOW_SENSOR_ID": "true", "PYTHONUNBUFFERED": "1"})
            process = subprocess.Popen(["/bin/bash", str(self.ds_start)], cwd=self.ds_start.parent, env=env)
            with self.lock:
                self.process = process
                self.status = "running"
            finished_at: float | None = None
            deadline = time.monotonic() + MAX_RUNTIME_SECONDS
            while time.monotonic() < deadline:
                messages = consumer.poll(timeout_ms=500)
                for records in messages.values():
                    for record in records:
                        try:
                            frame = MessageToDict(schema_pb2.Frame.FromString(record.value), preserving_proto_field_name=True)
                        except Exception:
                            continue
                        detected = candidate_from_frame(job_id, frame)
                        with self.lock:
                            self.frames += 1
                            self.objects += len(frame.get("objects", []))
                            if detected is not None and self.candidate is None:
                                self.candidate = detected
                        consumer.commit()
                return_code = process.poll()
                if return_code is not None:
                    if finished_at is None:
                        finished_at = time.monotonic()
                    if time.monotonic() - finished_at >= 3:
                        break
                if self.stop_requested.is_set():
                    break
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=20)
            with self.lock:
                self.status = "completed" if self.candidate else "no_candidate"
                self.completed_at = utc_now()
        except Exception as error:
            with self.lock:
                self.status = "failed"
                self.error = type(error).__name__
                self.completed_at = utc_now()
        finally:
            if consumer is not None:
                consumer.close()
            with self.lock:
                self.process = None

    def stop(self) -> None:
        self.stop_requested.set()
        with self.lock:
            process = self.process
        if process is not None and process.poll() is None:
            process.terminate()


class Handler(BaseHTTPRequestHandler):
    runtime: BatchRuntime

    def _json(self, status: int, value: Any) -> None:
        body = json.dumps(value, separators=(",", ":"), allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path in {"/health/live", "/health/ready", "/api/v1/state"}:
            self._json(200, self.runtime.snapshot())
            return
        match = re.fullmatch(r"/api/v1/jobs/([0-9a-f]{64})", path)
        if match and self.runtime.job_id == match.group(1):
            self._json(200, self.runtime.snapshot())
            return
        self._json(404, {"status": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        match = re.fullmatch(r"/api/v1/jobs/([0-9a-f]{64})/run", path)
        if not match:
            self._json(404, {"status": "not_found"})
            return
        try:
            self._json(202, self.runtime.start(match.group(1)))
        except FileNotFoundError as error:
            self._json(404, {"status": "error", "code": "media_not_found", "message": str(error)})
        except (RuntimeError, ValueError) as error:
            self._json(409, {"status": "error", "code": "job_not_ready", "message": str(error)})

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> int:
    runtime = BatchRuntime()
    Handler.runtime = runtime
    server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("HTTP_PORT", "39620"))), Handler)

    def request_shutdown(_signum: int, _frame: object) -> None:
        runtime.stop()
        # BaseServer.shutdown() must run outside the signal handler's serving
        # thread or it can wait on itself indefinitely.
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    try:
        server.serve_forever()
    finally:
        runtime.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
