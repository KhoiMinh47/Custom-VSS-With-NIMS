from __future__ import annotations

import json
import hashlib
import os
import re
import signal
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

from confluent_kafka import Consumer, KafkaError, Producer

from contracts import (
    PROMPT_VERSION,
    SCHEMA_VERSION,
    VERDICTS,
    VERIFIER_MODEL_ID,
    build_verified,
    confusion_matrix,
    parse_verdict,
    retry_operation,
    utc_now,
    validate_incident,
)
from vlm_client import CosmosClient, VLMError


TEST_ID_PATTERN = re.compile(r"[0-9a-f]{64}")
TEST_URI_PATTERN = re.compile(r"vlm-(stage|store)://([0-9a-f]{64})(\.mp4|\.mkv)")


def log(level: str, event: str, **fields: object) -> None:
    print(
        json.dumps(
            {
                "timestamp": utc_now(),
                "level": level,
                "service": "phase10-alert-verification",
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


def selected_clip_path(root: Path, incident: dict[str, Any]) -> Path:
    validate_incident(incident)
    expected = f'{incident["incident_id"]}.mp4'
    if str(incident["asset_uri"]) != f"selected-clip://{expected}":
        raise ValueError("selected clip URI does not match incident_id")
    return root / expected


def test_clip_path(root: Path, payload: dict[str, Any]) -> Path:
    required = (
        "schema_version",
        "store_id",
        "camera_id",
        "job_id",
        "source_type",
        "event_type",
        "start_time",
        "end_time",
        "asset_uri",
        "asset_sha256",
    )
    missing = [name for name in required if name not in payload]
    if missing:
        raise ValueError(f"VLM test request missing fields: {','.join(missing)}")
    if payload["schema_version"] != SCHEMA_VERSION or payload["store_id"] != "store-001":
        raise ValueError("VLM test identity is invalid")
    if not re.fullmatch(r"cam-[0-9]{2}", str(payload["camera_id"])):
        raise ValueError("VLM test camera_id is invalid")
    if TEST_ID_PATTERN.fullmatch(str(payload["job_id"])) is None:
        raise ValueError("VLM test job_id is invalid")
    if TEST_ID_PATTERN.fullmatch(str(payload["asset_sha256"])) is None:
        raise ValueError("VLM test asset_sha256 is invalid")
    try:
        start = datetime.fromisoformat(str(payload["start_time"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(payload["end_time"]).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("VLM test timestamps are invalid") from error
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        raise ValueError("VLM test timestamps must be UTC and ordered")
    match = TEST_URI_PATTERN.fullmatch(str(payload["asset_uri"]))
    if match is None:
        raise ValueError("VLM test asset_uri is invalid")
    kind, identifier, extension = match.groups()
    if kind == "stage" and identifier != payload["job_id"]:
        raise ValueError("VLM test staging URI does not match job_id")
    if kind == "store" and str(payload.get("parent_store_asset_id", identifier)) != identifier:
        raise ValueError("VLM test Store URI does not match asset ID")
    base = (root / ("staging" if kind == "stage" else "store")).resolve()
    path = (base / f"{identifier}{extension}").resolve()
    if path.parent != base:
        raise ValueError("VLM test media path escaped its allowlisted plane")
    if not path.is_file():
        raise FileNotFoundError("VLM test media is missing")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != payload["asset_sha256"]:
        raise ValueError("VLM test media digest does not match the contract")
    return path


def load_prompts(path: Path, event_type: str) -> tuple[str, str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    system = str(value["system"])
    prompt = value.get("event_types", {}).get(event_type, value["default"])
    return system, str(prompt)


class Runtime:
    def __init__(self) -> None:
        bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092")
        self.lock = threading.RLock()
        # The Cosmos provider is shared by the Kafka verifier and the
        # explicit VLM-test endpoint. A single local GPU lease must therefore
        # also imply one in-flight video request.
        self.vlm_lock = threading.Lock()
        self.ready = False
        self.started = time.monotonic()
        self.incidents_seen = 0
        self.verified = 0
        self.confirmed = 0
        self.rejected = 0
        self.uncertain = 0
        self.retries = 0
        self.dlq = 0
        self.last_latency_ms = 0
        self.last_alert: dict[str, Any] | None = None
        self.es_url = os.environ.get("ELASTICSEARCH_URL", "http://127.0.0.1:9200")
        self.output_topic = os.environ.get("OUTPUT_TOPIC", "vss.incidents.verified")
        self.dlq_topic = os.environ.get("DLQ_TOPIC", "vss.dlq")
        self.clip_root = Path(os.environ.get("SELECTED_CLIP_DIR", "/runtime/clips"))
        self.vlm_test_root = Path(
            os.environ.get("VLM_TEST_DIR", "/runtime/phase15/vlm-test")
        )
        self.prompt_path = Path(
            os.environ.get("PROMPT_CONFIG", "/config/prompts/verification.json")
        )
        self.admission_lease = Path(
            os.environ.get("ADMISSION_LEASE", "/runtime/admission/local-vlm.lease")
        )
        self.max_attempts = int(os.environ.get("VLM_ATTEMPTS", "3"))
        self.client = CosmosClient(
            os.environ.get("VLM_BASE_URL", "http://127.0.0.1:30082/v1"),
            os.environ.get("VLM_MODEL", VERIFIER_MODEL_ID),
            float(os.environ.get("VLM_TIMEOUT_SECONDS", "180")),
        )
        self.producer = Producer({"bootstrap.servers": bootstrap})

    def admitted(self) -> bool:
        try:
            lease = json.loads(self.admission_lease.read_text(encoding="utf-8"))
            return (
                lease.get("schema_version") == SCHEMA_VERSION
                and lease.get("profile") == "local_vlm"
                and lease.get("status") == "granted"
            )
        except (OSError, json.JSONDecodeError):
            return False

    def state(self) -> dict[str, Any]:
        with self.lock:
            admitted = self.admitted()
            vlm_ready = self.client.ready() if admitted else False
            return {
                "schema_version": SCHEMA_VERSION,
                "ready": self.ready,
                "store_id": "store-001",
                "camera_id": "cam-01",
                "uptime_seconds": round(time.monotonic() - self.started, 3),
                "admission_status": "granted" if admitted else "waiting",
                "vlm_status": "ready" if vlm_ready else "unavailable",
                "verifier_model_id": VERIFIER_MODEL_ID,
                "prompt_version": PROMPT_VERSION,
                "incidents_seen": self.incidents_seen,
                "verified": self.verified,
                "confirmed": self.confirmed,
                "rejected": self.rejected,
                "uncertain": self.uncertain,
                "retries": self.retries,
                "dlq": self.dlq,
                "last_latency_ms": self.last_latency_ms,
                "last_alert": self.last_alert,
            }

    def verify(self, incident: dict[str, Any]) -> dict[str, Any]:
        validate_incident(incident)
        clip = selected_clip_path(self.clip_root, incident)
        system, user = load_prompts(self.prompt_path, str(incident["event_type"]))
        user = user.format(
            event_type=incident["event_type"],
            camera_id=incident["camera_id"],
            start_time=incident["start_time"],
            end_time=incident["end_time"],
        )
        started = time.monotonic()
        def operation() -> str:
            if not self.admitted():
                raise VLMError("local VLM admission lease is absent")
            if not self.client.ready():
                raise VLMError("Cosmos3 readiness check failed")
            return self.client.verify(clip, system, user)

        def pause(attempt: int) -> None:
            with self.lock:
                self.retries += 1
            time.sleep(min(2 ** (attempt - 1), 4))

        with self.vlm_lock:
            response, retry_count, last_error = retry_operation(
                operation, attempts=self.max_attempts, pause=pause
            )
        if response is not None:
            verdict, confidence, reason = parse_verdict(response)
            alert = build_verified(
                incident,
                verdict=verdict,
                confidence=confidence,
                reason=reason,
                retry_count=retry_count,
                latency_ms=round((time.monotonic() - started) * 1000),
                raw_response=response,
            )
        else:
            alert = build_verified(
                incident,
                verdict="uncertain",
                confidence=0,
                reason=f"verification unavailable after retries ({last_error})",
                retry_count=self.max_attempts,
                latency_ms=round((time.monotonic() - started) * 1000),
            )
            self.producer.produce(
                self.dlq_topic,
                key=incident["incident_id"],
                value=json.dumps(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "source_service": "phase10-alert-verification",
                        "reason": "vlm_verification_exhausted",
                        "incident": incident,
                    },
                    separators=(",", ":"),
                ),
            )
            with self.lock:
                self.dlq += 1

        es_request(
            self.es_url,
            "PUT",
            f'/mdx-vlm-incidents/_doc/{alert["incident_id"]}',
            alert,
        )
        es_request(
            self.es_url,
            "PUT",
            f'/mdx-incidents/_doc/{alert["incident_id"]}',
            {**incident, "status": alert["status"], "verdict": alert["verdict"], "updated_at": alert["updated_at"]},
        )
        self.producer.produce(
            self.output_topic,
            key=alert["incident_id"],
            value=json.dumps(alert, separators=(",", ":")),
        )
        self.producer.flush(10)
        with self.lock:
            self.incidents_seen += 1
            self.verified += 1
            self.last_latency_ms = alert["latency_ms"]
            self.last_alert = alert
            setattr(self, str(alert["verdict"]), getattr(self, str(alert["verdict"])) + 1)
        log(
            "info",
            "verification_complete",
            incident_id=alert["incident_id"],
            verdict=alert["verdict"],
            retry_count=alert["retry_count"],
            latency_ms=alert["latency_ms"],
        )
        return alert

    def verify_test(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run one explicit VLM-test without publishing a production alert.

        The caller owns the durable test registry. This service is deliberately
        limited to the admission-controlled Cosmos invocation and contract
        validation, so the raw/video plane cannot become a metadata shortcut.
        """
        clip = test_clip_path(self.vlm_test_root, payload)
        if not self.admitted():
            raise VLMError("local VLM admission lease is absent")
        if not self.client.ready():
            raise VLMError("Cosmos3 readiness check failed")
        system, user = load_prompts(self.prompt_path, str(payload["event_type"]))
        user = user.format(
            event_type=payload["event_type"],
            camera_id=payload["camera_id"],
            start_time=payload["start_time"],
            end_time=payload["end_time"],
        )
        started = time.monotonic()

        def operation() -> str:
            if not self.admitted():
                raise VLMError("local VLM admission lease is absent")
            return self.client.verify(clip, system, user)

        def pause(_attempt: int) -> None:
            time.sleep(1)

        with self.vlm_lock:
            response, retry_count, last_error = retry_operation(
                operation, attempts=self.max_attempts, pause=pause
            )
        if response is None:
            raise VLMError(f"VLM test failed after retries ({last_error})")
        verdict, confidence, reason = parse_verdict(response)
        completed_at = utc_now()
        return {
            "schema_version": SCHEMA_VERSION,
            "store_id": "store-001",
            "camera_id": payload["camera_id"],
            "status": "completed",
            "job_id": payload["job_id"],
            "candidate_id": payload.get("candidate_id", payload["job_id"]),
            "source_type": payload["source_type"],
            "event_type": payload["event_type"],
            "start_time": payload["start_time"],
            "end_time": payload["end_time"],
            "asset_uri": payload["asset_uri"],
            "asset_sha256": payload["asset_sha256"],
            "verdict": verdict,
            "confidence": confidence,
            "reason": reason,
            "verifier_model_id": VERIFIER_MODEL_ID,
            "verifier_model_version": "bf16-final",
            "prompt_version": PROMPT_VERSION,
            "retry_count": retry_count,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "completed_at": completed_at,
            "raw_response_excerpt": response[:1000],
        }

    def alerts(self, size: int = 100) -> list[dict[str, Any]]:
        response = es_request(
            self.es_url,
            "POST",
            "/mdx-vlm-incidents/_search",
            {"size": min(max(size, 1), 500), "sort": [{"@timestamp": {"order": "desc"}}]},
        )
        return [hit["_source"] for hit in response.get("hits", {}).get("hits", [])]

    def feedback(self, incident_id: str, label: str, note: str = "") -> dict[str, Any]:
        if label not in VERDICTS:
            raise ValueError("feedback_label must be confirmed, rejected or uncertain")
        current = es_request(
            self.es_url, "GET", f"/mdx-vlm-incidents/_doc/{incident_id}"
        )["_source"]
        current["feedback_label"] = label
        current["feedback_at"] = utc_now()
        current["feedback_note"] = note[:1000]
        es_request(
            self.es_url, "PUT", f"/mdx-vlm-incidents/_doc/{incident_id}", current
        )
        return current


DASHBOARD_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Phase 10 verified alerts</title><style>
body{margin:0;background:#071018;color:#edf6ff;font:14px system-ui}
main{max-width:1380px;margin:auto;padding:18px}.cards{display:grid;
grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.card,section{background:#111d28;border:1px solid #294052;border-radius:10px;padding:12px}
.value{font-size:26px;color:#73efb2}section{margin-top:12px}table{width:100%;
border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #263846;text-align:left}
.confirmed{color:#73efb2}.rejected{color:#ff8f8f}.uncertain{color:#ffd27d}
button{margin:2px;padding:5px 8px}video{width:320px;max-height:180px;background:#000}
</style></head><body><main><h1>cam-01 · Phase 10 alert verification</h1>
<p id="status">Connecting…</p><div class="cards">
<div class="card">Verified<div id="verified" class="value">—</div></div>
<div class="card">Confirmed<div id="confirmed" class="value">—</div></div>
<div class="card">Rejected<div id="rejected" class="value">—</div></div>
<div class="card">Uncertain<div id="uncertain" class="value">—</div></div></div>
<section><h2>Review queue</h2><table><thead><tr><th>UTC / type</th><th>Clip</th>
<th>Verdict</th><th>Reason</th><th>Feedback label</th></tr></thead><tbody id="rows">
</tbody></table></section>
</main><script>
async function feedback(id,label){await fetch(`/api/v1/alerts/${id}/feedback`,{method:"POST",
headers:{"Content-Type":"application/json"},body:JSON.stringify({feedback_label:label})});poll()}
function esc(v){const d=document.createElement("div");d.textContent=String(v??"");return d.innerHTML}
async function poll(){try{const [s,a]=await Promise.all([fetch("/api/v1/state"),
fetch("/api/v1/alerts")]);const state=await s.json(),alerts=(await a.json()).alerts;
status.textContent=`admission ${state.admission_status} · Cosmos3 ${state.vlm_status} · retries ${state.retries}`;
verified.textContent=state.verified;confirmed.textContent=state.confirmed;rejected.textContent=state.rejected;
uncertain.textContent=state.uncertain;rows.innerHTML=alerts.map(x=>`<tr><td>${esc(x["@timestamp"])}
<br>${esc(x.event_type)}</td><td><video controls preload="metadata" src="/media/${x.incident_id}.mp4"></video></td>
<td class="${esc(x.verdict)}">${esc(x.verdict)}<br>${Math.round(100*(x.confidence||0))}%</td>
<td>${esc(x.reason)}</td><td>${esc(x.feedback_label||"unlabeled")}<br>
${["confirmed","rejected","uncertain"].map(v=>`<button onclick="feedback('${x.incident_id}','${v}')">${v}</button>`).join("")}
</td></tr>`).join("")}
catch(_){status.textContent="Review API unavailable; video/RT-CV planes remain independent"}
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
        elif path == "/api/v1/alerts":
            query = parse_qs(urlsplit(self.path).query)
            alerts = self.runtime.alerts(int(query.get("size", ["100"])[0]))
            self._json(200, {"alerts": alerts, "count": len(alerts)})
        elif path == "/api/v1/evaluation":
            alerts = self.runtime.alerts(500)
            labeled = sum(1 for item in alerts if item.get("feedback_label") in VERDICTS)
            latencies = sorted(int(item.get("latency_ms", 0)) for item in alerts)
            self._json(
                200,
                {
                    "schema_version": SCHEMA_VERSION,
                    "labeled_alerts": labeled,
                    "confusion_matrix": confusion_matrix(alerts),
                    "latency_ms": {
                        "count": len(latencies),
                        "p50": latencies[len(latencies) // 2] if latencies else 0,
                        "max": max(latencies, default=0),
                    },
                },
            )
        elif path == "/metrics":
            state = self.runtime.state()
            names = ("verified", "confirmed", "rejected", "uncertain", "retries", "dlq")
            content = (
                "\n".join(f"phase10_alert_{name}_total {state[name]}" for name in names)
                + f"\nphase10_alert_last_latency_ms {state['last_latency_ms']}\n"
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
        elif path.startswith("/media/") and path.endswith(".mp4"):
            name = path.removeprefix("/media/")
            if (
                len(name) != 68
                or not name.endswith(".mp4")
                or any(character not in "0123456789abcdef" for character in name[:-4])
            ):
                self.send_error(404)
                return
            clip = self.runtime.clip_root / name
            if not clip.is_file():
                self.send_error(404)
                return
            content = clip.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "private, max-age=60")
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if urlsplit(self.path).path == "/api/v1/vlm-tests/verify":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 2 or length > 256 * 1024:
                    raise ValueError("invalid payload size")
                value = json.loads(self.rfile.read(length))
                if not isinstance(value, dict):
                    raise ValueError("request body must be an object")
                self._json(200, self.runtime.verify_test(value))
            except VLMError as error:
                provider_wait = "admission" in str(error).lower() or "readiness" in str(error).lower()
                self._json(
                    503 if provider_wait else 502,
                    {
                        "schema_version": SCHEMA_VERSION,
                        "store_id": "store-001",
                        "status": "waiting_for_provider" if provider_wait else "failed",
                        "code": "provider_standby" if provider_wait else "vlm_test_failed",
                        "message": str(error)[:200],
                    },
                )
            except FileNotFoundError as error:
                self._json(404, {"status": "error", "code": "media_not_found", "message": str(error)})
            except (ValueError, KeyError, json.JSONDecodeError) as error:
                self._json(400, {"status": "rejected", "error": str(error)[:200]})
            except Exception as error:
                self._json(502, {"status": "error", "code": "vlm_test_failed", "error_type": type(error).__name__})
            return
        parts = urlsplit(self.path).path.strip("/").split("/")
        if len(parts) != 5 or parts[:3] != ["api", "v1", "alerts"] or parts[4] != "feedback":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            value = json.loads(self.rfile.read(length))
            updated = self.runtime.feedback(
                parts[3], str(value.get("feedback_label", "")), str(value.get("note", ""))
            )
            self._json(200, updated)
        except (ValueError, KeyError, json.JSONDecodeError) as error:
            self._json(400, {"status": "rejected", "error": str(error)})

    def log_message(self, _format: str, *_args: object) -> None:
        return


def consume(runtime: Runtime, stop: threading.Event) -> None:
    consumer = Consumer(
        {
            "bootstrap.servers": os.environ.get(
                "KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092"
            ),
            "group.id": os.environ.get(
                "KAFKA_CONSUMER_GROUP", "phase10-alert-verification-v1"
            ),
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
            "max.poll.interval.ms": 900000,
        }
    )
    input_topic = os.environ.get("INPUT_TOPIC", "vss.incidents.candidate")
    consumer.subscribe([input_topic])
    runtime.ready = True
    log("info", "consumer_started", input_topic=input_topic, output_topic=runtime.output_topic)
    while not stop.is_set():
        if not runtime.admitted() or not runtime.client.ready():
            time.sleep(2)
            continue
        message = consumer.poll(1)
        if message is None:
            continue
        if message.error():
            if message.error().code() != KafkaError._PARTITION_EOF:
                log("error", "consume_failed", error_code=message.error().code())
            continue
        try:
            runtime.verify(json.loads(message.value()))
            consumer.commit(message=message, asynchronous=False)
        except (ValueError, json.JSONDecodeError) as error:
            runtime.producer.produce(
                runtime.dlq_topic,
                key="invalid-incident",
                value=json.dumps(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "source_service": "phase10-alert-verification",
                        "reason": type(error).__name__,
                    }
                ),
            )
            runtime.producer.flush(10)
            consumer.commit(message=message, asynchronous=False)
        except Exception as error:
            log("error", "verification_processing_failed", error_type=type(error).__name__)
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
    log(
        "info",
        "service_started",
        schema_version=SCHEMA_VERSION,
        verifier_model_id=VERIFIER_MODEL_ID,
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
