from __future__ import annotations

import json
import os
import signal
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

import yaml
from confluent_kafka import Consumer, KafkaError, Producer

from contracts import ANALYTICS_MODEL_VERSION, SCHEMA_VERSION, validate_config
from engine import BehaviorEngine


def log(level: str, event: str, **fields: object) -> None:
    print(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "level": level,
                "service": "phase09-behavior-analytics",
                "event": event,
                **fields,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


def load_config(source: Path, override: Path) -> dict[str, Any]:
    path = override if override.exists() else source
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("analytics config must be an object")
    validate_config(value)
    return value


class Runtime:
    def __init__(self, config: dict[str, Any], override_path: Path) -> None:
        self.lock = threading.RLock()
        self.engine = BehaviorEngine(config)
        self.override_path = override_path
        self.ready = False
        self.started = time.monotonic()
        self.consume_errors = 0
        self.elasticsearch_errors = 0
        self.kafka_publish_errors = 0
        self.last_input_monotonic = 0.0

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            value = self.engine.snapshot()
            value.update(
                {
                    "ready": self.ready,
                    "uptime_seconds": round(time.monotonic() - self.started, 3),
                    "last_input_age_seconds": (
                        round(time.monotonic() - self.last_input_monotonic, 3)
                        if self.last_input_monotonic
                        else -1
                    ),
                    "consume_errors": self.consume_errors,
                    "elasticsearch_errors": self.elasticsearch_errors,
                    "kafka_publish_errors": self.kafka_publish_errors,
                }
            )
            return value

    def update_config(self, config: dict[str, Any]) -> None:
        validate_config(config)
        with self.lock:
            current = int(self.engine.config["config_version"])
            if int(config["config_version"]) != current + 1:
                raise ValueError("config_version must increment exactly by one")
            if (
                config["store_id"] != self.engine.config["store_id"]
                or config["camera_id"] != self.engine.config["camera_id"]
            ):
                raise ValueError("store_id and camera_id are immutable")
            self.override_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.override_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(config, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.override_path)
            self.engine = BehaviorEngine(config)
            log("info", "config_updated", config_version=config["config_version"])


DASHBOARD_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Phase 09 retail traffic analytics</title>
<style>
body{margin:0;background:#081018;color:#edf6ff;font:14px system-ui}
main{max-width:1280px;margin:auto;padding:18px}.cards{display:grid;
grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.card,section{background:#111d28;border:1px solid #2b4050;border-radius:10px;padding:12px}
.value{font-size:28px;color:#73efb2}section{margin-top:12px}canvas{width:100%;
max-width:900px;aspect-ratio:16/9;background:#071018}table{width:100%;border-collapse:collapse}
td,th{padding:7px;border-bottom:1px solid #263846;text-align:left}.risk{color:#ffd27d}
</style></head><body><main>
<h1>cam-01 · Phase 09 behavior analytics</h1>
<p id="status" class="risk">Connecting…</p><div class="cards">
<div class="card">Entry<div id="entry" class="value">—</div></div>
<div class="card">Exit<div id="exit" class="value">—</div></div>
<div class="card">Active tracks<div id="tracks" class="value">—</div></div>
<div class="card">Queue<div id="queue" class="value">—</div></div>
<div class="card">Queue wait<div id="queueWait" class="value">—</div></div></div>
<section><h2>Metadata heatmap</h2><canvas id="heatmap"></canvas></section>
<section><h2>Recent events</h2><table><thead><tr><th>UTC</th><th>Type</th>
<th>Evidence</th></tr></thead><tbody id="events"></tbody></table></section>
</main><script>
const canvas=document.getElementById("heatmap"),ctx=canvas.getContext("2d");
function render(s){status.textContent=`${s.ready?"connected":"waiting"} · config v${s.config_version}
 · calibration ${s.calibration_status} · last input age ${s.last_input_age_seconds}s`;
entry.textContent=s.entry_count;exit.textContent=s.exit_count;tracks.textContent=s.active_tracks;
queue.textContent=s.queue_length;const h=s.heatmap,rect=canvas.getBoundingClientRect();
queueWait.textContent=`${s.estimated_queue_wait_seconds}s`;
canvas.width=Math.max(1,Math.round(rect.width));canvas.height=Math.max(1,Math.round(rect.width*9/16));
const cw=canvas.width/h.columns,ch=canvas.height/h.rows;
h.normalized.forEach((row,y)=>row.forEach((v,x)=>{ctx.fillStyle=`rgba(255,80,40,${.08+.92*v})`;
ctx.fillRect(x*cw,y*ch,cw,ch)}));events.innerHTML=(s.recent_events||[]).slice(0,30).map(e=>
`<tr><td>${e["@timestamp"]}</td><td>${e.event_type}</td><td>${e.evidence.frame_id}</td></tr>`).join("")}
async function poll(){try{const r=await fetch("/api/v1/state",{cache:"no-store"});
render(await r.json())}catch(_){status.textContent="analytics API unavailable; RT-CV/video are independent"}
finally{setTimeout(poll,1000)}}poll();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    runtime: Runtime

    def _json(self, status: int, body: Any) -> None:
        content = json.dumps(body, separators=(",", ":")).encode()
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
            snapshot = self.runtime.snapshot()
            self._json(
                200 if snapshot["ready"] else 503,
                {
                    "status": "ready" if snapshot["ready"] else "not_ready",
                    "schema_version": SCHEMA_VERSION,
                    "camera_id": snapshot["camera_id"],
                },
            )
        elif path == "/api/v1/state":
            self._json(200, self.runtime.snapshot())
        elif path == "/api/v1/config":
            with self.runtime.lock:
                self._json(200, self.runtime.engine.config)
        elif path == "/api/v1/events":
            query = parse_qs(urlsplit(self.path).query)
            include_evaluation = query.get("include_evaluation", ["false"])[0] == "true"
            with self.runtime.lock:
                events = [
                    event
                    for event in self.runtime.engine.recent_events
                    if include_evaluation or not event["evaluation"]
                ]
            self._json(200, {"events": events[:100], "count": len(events[:100])})
        elif path in {"/", "/dashboard"}:
            content = DASHBOARD_HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)
        elif path == "/metrics":
            snapshot = self.runtime.snapshot()
            names = (
                ("behavior_frames_total", "frames_processed"),
                ("behavior_events_total", "events_emitted"),
                ("behavior_entry_total", "entry_count"),
                ("behavior_exit_total", "exit_count"),
                ("behavior_active_tracks", "active_tracks"),
                ("behavior_queue_length", "queue_length"),
                ("behavior_consume_errors_total", "consume_errors"),
                ("behavior_elasticsearch_errors_total", "elasticsearch_errors"),
                ("behavior_kafka_publish_errors_total", "kafka_publish_errors"),
            )
            lines = [
                f'{metric}{{camera_id="{snapshot["camera_id"]}"}} {snapshot[field]}'
                for metric, field in names
            ]
            content = ("\n".join(lines) + "\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(404)

    def do_PUT(self) -> None:  # noqa: N802
        if urlsplit(self.path).path != "/api/v1/config":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > 256 * 1024:
                raise ValueError("invalid config payload size")
            config = json.loads(self.rfile.read(length))
            if not isinstance(config, dict):
                raise ValueError("config must be an object")
            self.runtime.update_config(config)
            self._json(200, {"status": "updated", "config_version": config["config_version"]})
        except (ValueError, json.JSONDecodeError) as error:
            self._json(400, {"status": "rejected", "error": str(error)})

    def log_message(self, _format: str, *_args: object) -> None:
        return


def es_put(base_url: str, event: dict[str, Any]) -> None:
    request = Request(
        f'{base_url.rstrip("/")}/vss-behavior-events/_doc/{event["event_id"]}',
        data=json.dumps(event, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    for attempt in range(3):
        try:
            with urlopen(request, timeout=5) as response:
                if response.status in {200, 201}:
                    return
        except Exception:
            if attempt < 2:
                time.sleep(0.1 * (attempt + 1))
    raise RuntimeError("Elasticsearch write failed")


def consume(runtime: Runtime, stop: threading.Event) -> None:
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    input_topic = os.environ.get("INPUT_TOPIC", "vss.rt-cv.frames")
    output_topic = os.environ.get("OUTPUT_TOPIC", "vss.behavior.events")
    dlq_topic = os.environ.get("DLQ_TOPIC", "vss.dlq")
    es_url = os.environ.get("ELASTICSEARCH_URL", "http://elasticsearch:9200")
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": os.environ.get(
                "KAFKA_CONSUMER_GROUP", "phase09-behavior-analytics-v1"
            ),
            "auto.offset.reset": "latest",
            "enable.auto.commit": False,
        }
    )
    producer = Producer({"bootstrap.servers": bootstrap})
    consumer.subscribe([input_topic])
    runtime.ready = True
    log("info", "consumer_started", input_topic=input_topic, output_topic=output_topic)
    while not stop.is_set():
        message = consumer.poll(1.0)
        if message is None:
            continue
        if message.error():
            if message.error().code() != KafkaError._PARTITION_EOF:
                with runtime.lock:
                    runtime.consume_errors += 1
                log("error", "broker_consume_failed", error_code=message.error().code())
            continue
        try:
            frame = json.loads(message.value())
            with runtime.lock:
                events = runtime.engine.process_frame(frame)
                runtime.last_input_monotonic = time.monotonic()
            for event in events:
                try:
                    es_put(es_url, event)
                except RuntimeError:
                    with runtime.lock:
                        runtime.elasticsearch_errors += 1
                    producer.produce(
                        dlq_topic,
                        key=event["event_id"],
                        value=json.dumps(
                            {
                                "schema_version": SCHEMA_VERSION,
                                "source_service": "phase09-behavior-analytics",
                                "reason": "elasticsearch_write_failed",
                                "event": event,
                            },
                            separators=(",", ":"),
                        ),
                    )
                    continue
                producer.produce(
                    output_topic,
                    key=event["event_id"],
                    value=json.dumps(event, separators=(",", ":")),
                )
            producer.poll(0)
            consumer.commit(message=message, asynchronous=False)
        except Exception as error:
            with runtime.lock:
                runtime.consume_errors += 1
            log("error", "frame_processing_failed", error_type=type(error).__name__)
            consumer.commit(message=message, asynchronous=False)
    producer.flush(10)
    consumer.close()
    runtime.ready = False
    log("info", "consumer_stopped")


def main() -> int:
    source = Path(os.environ.get("ANALYTICS_CONFIG", "/config/cam-01.behavior.yaml"))
    override = Path(os.environ.get("ANALYTICS_CONFIG_OVERRIDE", "/runtime/config.json"))
    runtime = Runtime(load_config(source, override), override)
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
    log(
        "info",
        "service_started",
        schema_version=SCHEMA_VERSION,
        model_version=ANALYTICS_MODEL_VERSION,
    )
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
