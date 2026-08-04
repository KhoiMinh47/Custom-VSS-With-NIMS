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

from kafka import KafkaConsumer

from contracts import (
    MODEL_ID,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    VERDICTS,
    build_direct_alert,
    confusion_matrix,
    utc_now,
)


def log(level: str, event: str, **fields: object) -> None:
    print(
        json.dumps(
            {
                "timestamp": utc_now(),
                "level": level,
                "service": "phase11-rt-vlm-results",
                "event": event,
                **fields,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


def es_request(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=None if payload is None else json.dumps(payload, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urlopen(request, timeout=10) as response:
        body = response.read()
    return json.loads(body) if body else {}


def timestamp_text(value: object, fallback: str) -> str:
    seconds = int(getattr(value, "seconds", 0))
    nanos = int(getattr(value, "nanos", 0))
    if seconds <= 0:
        return fallback
    parsed = datetime.fromtimestamp(seconds + nanos / 1_000_000_000, UTC)
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def decode_vision_llm(payload: bytes) -> dict[str, Any]:
    # The collector runs in the pinned VSS RT-VLM image and therefore uses the
    # exact generated protobuf contract shipped with release 3.2.1.
    from server.protos import nv_pb2

    message = nv_pb2.VisionLLM()
    message.ParseFromString(payload)
    if not message.llm.queries:
        raise ValueError("VisionLLM message has no query")
    query = message.llm.queries[0]
    info = dict(message.info)
    params = dict(query.params)
    now = utc_now()
    return {
        "request_id": params.get("requestId") or info.get("requestId") or query.id,
        "chunk_index": int(params.get("chunkIdx") or info.get("chunkIdx") or 0),
        "camera_id": params.get("cameraId") or info.get("cameraId") or message.sensor.id,
        "start_time": timestamp_text(message.timestamp, now),
        "end_time": timestamp_text(message.end, now),
        "response": query.response,
        "model_version": message.version or message.llm.info.get("modelId", ""),
        "info": info,
    }


class Runtime:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.ready = False
        self.started = time.monotonic()
        self.messages_seen = 0
        self.persisted = 0
        self.decode_errors = 0
        self.persist_errors = 0
        self.confirmed = 0
        self.rejected = 0
        self.uncertain = 0
        self.last_alert: dict[str, Any] | None = None
        self.es_url = os.environ.get("ELASTICSEARCH_URL", "http://127.0.0.1:9200")
        self.rt_vlm_url = os.environ.get("RT_VLM_URL", "http://rt-vlm:8000")
        self.resource_metrics_path = Path(
            os.environ.get(
                "RESOURCE_METRICS_PATH",
                "/opt/ntc/runtime/resource-metrics.json",
            )
        )

    def direct_ready(self) -> bool:
        try:
            with urlopen(f"{self.rt_vlm_url}/v1/ready", timeout=3) as response:
                return response.status == 200
        except Exception:
            return False

    def state(self) -> dict[str, Any]:
        with self.lock:
            return {
                "schema_version": SCHEMA_VERSION,
                "ready": self.ready,
                "store_id": "store-001",
                "camera_id": "cam-01",
                "uptime_seconds": round(time.monotonic() - self.started, 3),
                "direct_rt_vlm_status": "ready" if self.direct_ready() else "stopped",
                "model_id": MODEL_ID,
                "prompt_version": PROMPT_VERSION,
                "messages_seen": self.messages_seen,
                "persisted": self.persisted,
                "confirmed": self.confirmed,
                "rejected": self.rejected,
                "uncertain": self.uncertain,
                "decode_errors": self.decode_errors,
                "persist_errors": self.persist_errors,
                "last_alert": self.last_alert,
            }

    def resources(self) -> dict[str, Any]:
        try:
            value = json.loads(self.resource_metrics_path.read_text(encoding="utf-8"))
            timestamp = datetime.fromisoformat(
                str(value["timestamp"]).replace("Z", "+00:00")
            )
            value["available"] = True
            value["stale"] = (datetime.now(UTC) - timestamp).total_seconds() > 10
            return value
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return {
                "schema_version": SCHEMA_VERSION,
                "available": False,
                "stale": True,
            }

    def persist(self, decoded: dict[str, Any]) -> dict[str, Any]:
        alert = build_direct_alert(**decoded)
        es_request(
            self.es_url,
            "PUT",
            f'/mdx-rt-vlm-alerts/_doc/{alert["direct_alert_id"]}',
            alert,
        )
        with self.lock:
            self.persisted += 1
            self.last_alert = alert
            verdict = str(alert["verdict"])
            setattr(self, verdict, getattr(self, verdict) + 1)
        log(
            "info",
            "direct_alert_persisted",
            direct_alert_id=alert["direct_alert_id"],
            camera_id=alert["camera_id"],
            verdict=alert["verdict"],
            latency_ms=alert["latency_ms"],
            frame_count=alert["frame_count"],
        )
        return alert

    def alerts(self, size: int = 100) -> list[dict[str, Any]]:
        response = es_request(
            self.es_url,
            "POST",
            "/mdx-rt-vlm-alerts/_search",
            {"size": min(max(size, 1), 500), "sort": [{"@timestamp": {"order": "desc"}}]},
        )
        return [hit["_source"] for hit in response.get("hits", {}).get("hits", [])]

    def feedback(self, direct_alert_id: str, label: str, note: str) -> dict[str, Any]:
        if label not in VERDICTS:
            raise ValueError("feedback_label must be confirmed, rejected or uncertain")
        current = es_request(
            self.es_url, "GET", f"/mdx-rt-vlm-alerts/_doc/{direct_alert_id}"
        )["_source"]
        current["feedback_label"] = label
        current["feedback_at"] = utc_now()
        current["feedback_note"] = note[:1000]
        es_request(
            self.es_url, "PUT", f"/mdx-rt-vlm-alerts/_doc/{direct_alert_id}", current
        )
        return current

    def comparison(self) -> dict[str, Any]:
        direct = self.alerts(500)
        hybrid_response = es_request(
            self.es_url,
            "POST",
            "/mdx-vlm-incidents/_search",
            {"size": 500, "query": {"match_all": {}}},
        )
        hybrid = [
            hit["_source"]
            for hit in hybrid_response.get("hits", {}).get("hits", [])
        ]

        def summary(values: list[dict[str, Any]]) -> dict[str, Any]:
            latencies = sorted(int(item.get("latency_ms", 0)) for item in values)
            labels = [
                item for item in values if item.get("feedback_label") in VERDICTS
            ]
            disagreements = sum(
                item.get("feedback_label") != item.get("verdict") for item in labels
            )
            return {
                "samples": len(values),
                "labeled": len(labels),
                "false_alerts_or_disagreements": disagreements,
                "latency_ms": {
                    "p50": latencies[len(latencies) // 2] if latencies else 0,
                    "max": max(latencies, default=0),
                },
            }

        return {
            "schema_version": SCHEMA_VERSION,
            "direct": summary(direct),
            "hybrid": summary(hybrid),
            "accuracy_status": (
                "measured" if len([a for a in direct if a.get("feedback_label")]) >= 20
                else "insufficient_labels"
            ),
        }


DASHBOARD_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Phase 11 direct RT-VLM</title><style>
body{margin:0;background:#071018;color:#edf6ff;font:14px system-ui}
main{max-width:1380px;margin:auto;padding:18px}
section{background:#111d28;border:1px solid #294052;border-radius:10px;padding:12px}
section{margin-top:12px}table{width:100%;
border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #263846;text-align:left}
.confirmed{color:#73efb2}.rejected{color:#ff8f8f}.uncertain{color:#ffd27d}
.live{padding:0;overflow:hidden;background:#05090d}
.live h2{margin:0;padding:12px 14px}.live img{display:block;width:100%;max-height:72vh;
object-fit:contain;background:#000}.live-note{margin:0;padding:0 14px 12px;color:#9db0bf}
.event-time{font-variant-numeric:tabular-nums;white-space:nowrap}
</style></head><body><main>
<h1>cam-01 · Phase 11 direct RT-VLM</h1><p id="status">Connecting…</p>
<section class="live"><h2>Camera live 720p</h2>
<img src="http://127.0.0.1:8090/mjpeg" alt="Live video from cam-01">
<p class="live-note">Video trực tiếp vẫn hiển thị khi Cosmos3 đang khởi động hoặc tạm dừng.</p></section>
<section><h2>Direct semantic results</h2><table><thead><tr><th>Camera time</th>
<th>Verdict</th><th>Reason</th></tr></thead>
<tbody id="rows"></tbody></table></section></main><script>
function esc(v){const d=document.createElement("div");d.textContent=String(v??"");return d.innerHTML}
function cameraTime(value){const date=new Date(value);if(Number.isNaN(date.getTime()))return String(value??"—");
const parts=new Intl.DateTimeFormat("en-US",{timeZone:"Asia/Ho_Chi_Minh",month:"2-digit",
day:"2-digit",year:"numeric",weekday:"short",hour:"2-digit",minute:"2-digit",second:"2-digit",
hour12:false}).formatToParts(date).reduce((out,part)=>(out[part.type]=part.value,out),{});
return `${parts.month}-${parts.day}-${parts.year} ${parts.weekday} ${parts.hour}:${parts.minute}:${parts.second}`}
async function poll(){try{const [s,a]=await Promise.all([fetch("/api/v1/state"),
fetch("/api/v1/alerts")]);const state=await s.json(),alerts=(await a.json()).alerts;
status.textContent=`RT-VLM ${state.direct_rt_vlm_status} · model ${state.model_id}`;
rows.innerHTML=alerts.map(x=>`<tr><td class="event-time">${esc(cameraTime(x.start_time))}</td>
<td class="${esc(x.verdict)}">${esc(x.verdict)}</td><td>${esc(x.reason)}</td></tr>`).join("");
}catch(_){status.textContent="Collector unavailable"}
finally{setTimeout(poll,2000)}}poll();</script></body></html>"""


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
            self._json(200, self.runtime.state())
        elif path == "/api/v1/resources":
            self._json(200, self.runtime.resources())
        elif path == "/api/v1/alerts":
            query = parse_qs(urlsplit(self.path).query)
            alerts = self.runtime.alerts(int(query.get("size", ["100"])[0]))
            self._json(200, {"alerts": alerts, "count": len(alerts)})
        elif path == "/api/v1/comparison":
            self._json(200, self.runtime.comparison())
        elif path == "/api/v1/evaluation":
            alerts = self.runtime.alerts(500)
            labels = [item for item in alerts if item.get("feedback_label") in VERDICTS]
            self._json(
                200,
                {
                    "schema_version": SCHEMA_VERSION,
                    "labeled_alerts": len(labels),
                    "confusion_matrix": confusion_matrix(alerts),
                    "accuracy_status": "measured" if len(labels) >= 20 else "insufficient_labels",
                },
            )
        elif path == "/metrics":
            state = self.runtime.state()
            names = (
                "messages_seen",
                "persisted",
                "confirmed",
                "rejected",
                "uncertain",
                "decode_errors",
                "persist_errors",
            )
            content = (
                "\n".join(f"phase11_rt_vlm_{name}_total {state[name]}" for name in names)
                + "\n"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        elif path in {"/", "/dashboard"}:
            content = DASHBOARD_HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        parts = urlsplit(self.path).path.strip("/").split("/")
        if len(parts) != 5 or parts[:3] != ["api", "v1", "alerts"] or parts[4] != "feedback":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > 64 * 1024:
                raise ValueError("invalid payload size")
            value = json.loads(self.rfile.read(length))
            updated = self.runtime.feedback(
                parts[3],
                str(value.get("feedback_label", "")),
                str(value.get("note", "")),
            )
            self._json(200, updated)
        except (ValueError, KeyError, json.JSONDecodeError) as error:
            self._json(400, {"status": "rejected", "error": str(error)})

    def log_message(self, _format: str, *_args: object) -> None:
        return


def consume(runtime: Runtime, stop: threading.Event) -> None:
    consumer = KafkaConsumer(
        os.environ.get("INPUT_TOPIC", "vss.rt-vlm.captions"),
        bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092"),
        group_id=os.environ.get("KAFKA_CONSUMER_GROUP", "phase11-direct-results-v1"),
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        consumer_timeout_ms=1000,
    )
    runtime.ready = True
    log("info", "consumer_started")
    while not stop.is_set():
        for message in consumer:
            if stop.is_set():
                break
            with runtime.lock:
                runtime.messages_seen += 1
            try:
                runtime.persist(decode_vision_llm(message.value))
                consumer.commit()
            except ValueError as error:
                with runtime.lock:
                    runtime.decode_errors += 1
                log("warning", "protobuf_rejected", error_type=type(error).__name__)
                consumer.commit()
            except Exception as error:
                with runtime.lock:
                    runtime.persist_errors += 1
                log("error", "result_processing_failed", error_type=type(error).__name__)
                time.sleep(2)
    consumer.close()
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
