from __future__ import annotations

import json
import os
import re
import signal
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from confluent_kafka import Consumer, KafkaError, Producer

from contracts import SCHEMA_VERSION, build_incident, is_candidate, mark_clip_ready
from media import MediaPreparationError, MediaPreparer, MediaSelectionError, ViosClipSelector


def log(level: str, event: str, **fields: object) -> None:
    print(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "level": level,
                "service": "phase10-incidents",
                "event": event,
                **fields,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


def es_put(base_url: str, alias: str, document_id: str, value: dict[str, Any]) -> None:
    request = Request(
        f"{base_url.rstrip('/')}/{alias}/_doc/{document_id}",
        data=json.dumps(value, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    with urlopen(request, timeout=10) as response:
        if response.status not in {200, 201}:
            raise RuntimeError(f"Elasticsearch returned {response.status}")


def es_request(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 10,
) -> dict[str, Any]:
    """Call the fixed local Elasticsearch API for candidate reads."""
    if not path.startswith("/") or "://" in path or "\r" in path or "\n" in path:
        raise ValueError("invalid Elasticsearch path")
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json" if body is not None else "application/json",
        },
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            content = response.read(2 * 1024 * 1024)
            status = int(response.status)
    except HTTPError as error:
        status = int(error.code)
        content = error.read(2 * 1024 * 1024)
        error.close()
        if status == 404:
            raise KeyError("Elasticsearch document not found") from error
        raise RuntimeError(f"Elasticsearch returned {status}") from error
    if status not in {200, 201}:
        raise RuntimeError(f"Elasticsearch returned {status}")
    value = json.loads(content) if content else {}
    if not isinstance(value, dict):
        raise RuntimeError("Elasticsearch returned a non-object response")
    return value


class Runtime:
    def __init__(self) -> None:
        bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092")
        self.lock = threading.RLock()
        self.ready = False
        self.started = time.monotonic()
        self.events_seen = 0
        self.events_filtered = 0
        self.incidents_prepared = 0
        self.clip_errors = 0
        self.publish_errors = 0
        self.last_incident: dict[str, Any] | None = None
        self.output_topic = os.environ.get("OUTPUT_TOPIC", "vss.incidents.candidate")
        self.dlq_topic = os.environ.get("DLQ_TOPIC", "vss.dlq")
        self.es_url = os.environ.get("ELASTICSEARCH_URL", "http://127.0.0.1:9200")
        self.selector = ViosClipSelector(
            os.environ.get("VIOS_BASE_URL", "http://127.0.0.1:30888/vst"),
            Path(os.environ.get("SELECTED_CLIP_DIR", "/runtime/clips")),
            timeout_seconds=float(os.environ.get("CLIP_TIMEOUT_SECONDS", "60")),
            attempts=int(os.environ.get("CLIP_ATTEMPTS", "4")),
        )
        self.preparer = MediaPreparer(
            os.environ.get("MEDIA_PREPARATION_URL", "http://media-preparation:8080")
        )
        self.pre_roll = float(os.environ.get("PRE_ROLL_SECONDS", "4"))
        self.post_roll = float(os.environ.get("POST_ROLL_SECONDS", "4"))
        self.producer = Producer({"bootstrap.servers": bootstrap})

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "schema_version": SCHEMA_VERSION,
                "ready": self.ready,
                "store_id": "store-001",
                "camera_id": "cam-01",
                "uptime_seconds": round(time.monotonic() - self.started, 3),
                "events_seen": self.events_seen,
                "events_filtered": self.events_filtered,
                "incidents_prepared": self.incidents_prepared,
                "clip_errors": self.clip_errors,
                "publish_errors": self.publish_errors,
                "last_incident": self.last_incident,
            }

    def process(self, event: dict[str, Any]) -> dict[str, Any] | None:
        with self.lock:
            self.events_seen += 1
        if not is_candidate(event):
            with self.lock:
                self.events_filtered += 1
            return None
        incident = build_incident(
            event,
            pre_roll_seconds=self.pre_roll,
            post_roll_seconds=self.post_roll,
        )
        es_put(self.es_url, "mdx-incidents", incident["incident_id"], incident)
        try:
            clip, _source_digest, _source_size = self.selector.select(incident)
            digest, size = self.preparer.prepare(clip)
            incident = mark_clip_ready(
                incident,
                asset_uri=f'selected-clip://{incident["incident_id"]}.mp4',
                clip_sha256=digest,
                clip_bytes=size,
            )
            es_put(self.es_url, "mdx-incidents", incident["incident_id"], incident)
            self.producer.produce(
                self.output_topic,
                key=incident["incident_id"],
                value=json.dumps(incident, separators=(",", ":")),
            )
            self.producer.flush(10)
        except (MediaSelectionError, MediaPreparationError):
            with self.lock:
                self.clip_errors += 1
            log(
                "warning",
                "clip_selection_delayed",
                incident_id=incident["incident_id"],
                camera_id=incident["camera_id"],
            )
            raise
        except Exception:
            with self.lock:
                self.publish_errors += 1
            raise
        with self.lock:
            self.incidents_prepared += 1
            self.last_incident = incident
        log(
            "info",
            "incident_queued",
            incident_id=incident["incident_id"],
            camera_id=incident["camera_id"],
            event_type=incident["event_type"],
            clip_bytes=incident["clip_bytes"],
        )
        return incident

    def to_dlq(self, reason: str, source: dict[str, Any]) -> None:
        self.producer.produce(
            self.dlq_topic,
            key=str(source.get("event_id", "invalid-event")),
            value=json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "source_service": "phase10-incidents",
                    "reason": reason,
                    "event": source,
                },
                separators=(",", ":"),
            ),
        )
        self.producer.flush(10)

    def candidates(self, limit: int = 50) -> list[dict[str, Any]]:
        size = min(max(int(limit), 1), 100)
        response = es_request(
            self.es_url,
            "POST",
            "/mdx-incidents/_search",
            {
                "size": size,
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"store_id": "store-001"}},
                            {"term": {"candidate": True}},
                        ]
                    }
                },
                "sort": [{"updated_at": {"order": "desc"}}],
            },
        )
        result: list[dict[str, Any]] = []
        for hit in response.get("hits", {}).get("hits", []):
            source = hit.get("_source") if isinstance(hit, dict) else None
            if not isinstance(source, dict):
                continue
            if (
                source.get("schema_version") == "1.0.0"
                and source.get("store_id") == "store-001"
                and re.fullmatch(r"cam-[0-9]{2}", str(source.get("camera_id", "")))
                and re.fullmatch(r"[0-9a-f]{64}", str(source.get("incident_id", "")))
            ):
                result.append(source)
        return result

    def candidate(self, incident_id: str) -> dict[str, Any]:
        if re.fullmatch(r"[0-9a-f]{64}", incident_id) is None:
            raise ValueError("invalid incident_id")
        response = es_request(self.es_url, "GET", f"/mdx-incidents/_doc/{incident_id}")
        source = response.get("_source") if isinstance(response, dict) else None
        if not isinstance(source, dict):
            raise KeyError("candidate not found")
        if source.get("store_id") != "store-001" or source.get("candidate") is not True:
            raise KeyError("candidate not found")
        return source


class Handler(BaseHTTPRequestHandler):
    runtime: Runtime

    def _json(self, status: int, value: Any) -> None:
        content = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/health/live":
            self._json(200, {"status": "ok", "schema_version": SCHEMA_VERSION})
        elif path == "/health/ready":
            self._json(
                200 if self.runtime.ready else 503,
                {"status": "ready" if self.runtime.ready else "not_ready"},
            )
        elif path == "/api/v1/state":
            self._json(200, self.runtime.snapshot())
        elif path == "/api/v1/candidates":
            from urllib.parse import parse_qs

            query = parse_qs(urlsplit(self.path).query)
            self._json(
                200,
                {
                    "schema_version": SCHEMA_VERSION,
                    "store_id": "store-001",
                    "candidates": self.runtime.candidates(int(query.get("limit", ["50"])[0])),
                },
            )
        elif re.fullmatch(r"/api/v1/candidates/[0-9a-f]{64}", path):
            self._json(
                200,
                {
                    "schema_version": SCHEMA_VERSION,
                    "store_id": "store-001",
                    "incident": self.runtime.candidate(path.rsplit("/", 1)[-1]),
                },
            )
        elif path == "/metrics":
            state = self.runtime.snapshot()
            lines = [
                f"phase10_incident_events_seen_total {state['events_seen']}",
                f"phase10_incidents_prepared_total {state['incidents_prepared']}",
                f"phase10_incident_clip_errors_total {state['clip_errors']}",
                f"phase10_incident_publish_errors_total {state['publish_errors']}",
            ]
            content = ("\n".join(lines) + "\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if urlsplit(self.path).path != "/api/v1/candidates":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > 256 * 1024:
                raise ValueError("invalid payload size")
            event = json.loads(self.rfile.read(length))
            if not isinstance(event, dict):
                raise ValueError("candidate must be an object")
            incident = self.runtime.process(event)
            self._json(202 if incident else 200, {"incident": incident, "filtered": not incident})
        except (ValueError, json.JSONDecodeError) as error:
            self._json(400, {"status": "rejected", "error": str(error)})
        except Exception as error:
            self._json(503, {"status": "retryable", "error_type": type(error).__name__})

    def log_message(self, _format: str, *_args: object) -> None:
        return


def consume(runtime: Runtime, stop: threading.Event) -> None:
    consumer = Consumer(
        {
            "bootstrap.servers": os.environ.get(
                "KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092"
            ),
            "group.id": os.environ.get("KAFKA_CONSUMER_GROUP", "phase10-incidents-v1"),
            "auto.offset.reset": "latest",
            "enable.auto.commit": False,
            "max.poll.interval.ms": 900000,
        }
    )
    input_topic = os.environ.get("INPUT_TOPIC", "vss.behavior.events")
    consumer.subscribe([input_topic])
    runtime.ready = True
    log("info", "consumer_started", input_topic=input_topic, output_topic=runtime.output_topic)
    while not stop.is_set():
        message = consumer.poll(1)
        if message is None:
            continue
        if message.error():
            if message.error().code() != KafkaError._PARTITION_EOF:
                log("error", "consume_failed", error_code=message.error().code())
            continue
        try:
            event = json.loads(message.value())
            runtime.process(event)
            consumer.commit(message=message, asynchronous=False)
        except (MediaSelectionError, MediaPreparationError):
            time.sleep(2)
        except (ValueError, json.JSONDecodeError) as error:
            source = locals().get("event", {})
            runtime.to_dlq(type(error).__name__, source if isinstance(source, dict) else {})
            consumer.commit(message=message, asynchronous=False)
        except Exception as error:
            log("error", "incident_processing_failed", error_type=type(error).__name__)
            time.sleep(2)
    consumer.close()
    runtime.producer.flush(10)
    runtime.ready = False


def main() -> int:
    runtime = Runtime()
    Handler.runtime = runtime
    stop = threading.Event()
    worker = threading.Thread(target=consume, args=(runtime, stop), daemon=True)
    worker.start()
    server = ThreadingHTTPServer(
        ("0.0.0.0", int(os.environ.get("HTTP_PORT", "8080"))), Handler
    )

    def shutdown(_signum: int, _frame: object) -> None:
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
